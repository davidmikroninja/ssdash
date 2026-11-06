#!/usr/bin/env python3
"""Generate a RouterOS address-list import for BadBox/Vo1d C2 destinations.

Reads ssdash's SQLite store (the Shadowserver ingest already running on the
same host) and emits an .rsc file that REPLACES the Dynamic_BadBox_C2 address
list on a RouterOS 7 router. The router fetches that file hourly (see
README.md), which is what removes the manual daily port edits.

Why destination addresses rather than ports: Shadowserver's sinkhole only
observes the ports its listeners cover, so the feed can never tell you which
port the bot moved to next. Destination addresses do not have that blind
spot, and the list rebuilds itself.

Usage:
    .venv/bin/python deploy/badbox/generate_c2_list.py \\
        --db data/shadowserver/shadowserver.db \\
        --out /srv/lists/badbox_c2.rsc

Two refusal conditions, both exiting non-zero and leaving the previous file
untouched (the router then keeps its current list):

  * no matching addresses in the window -- importing a file that starts with
    a remove and has nothing to add would empty the router's list and silently
    unblock everything;
  * the database itself is stale -- if the hourly ingest has quietly stopped,
    the generator would otherwise keep re-emitting yesterday's addresses
    forever and nothing would look wrong.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

LIST_NAME = "Dynamic_BadBox_C2"
DEFAULT_ISSUES = ("badbox", "vo1d")
LOOKBACK_DAYS = 7
MAX_STALENESS_DAYS = 2

EXIT_NO_ADDRESSES = 2
EXIT_STALE = 3


def c2_addresses(db_path: Path, days: int, issues: tuple[str, ...]) -> dict[str, int]:
    """Return {dst_ip: hit_count} for matching sinkhole events in the window."""
    # Report dates are Shadowserver's, i.e. UTC. Compare against UTC, not the
    # local date: on a host east of UTC the two differ by a day and the
    # staleness check would silently tighten or loosen depending on where the
    # cron happens to run.
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute(
            "SELECT issue, detail, report_date FROM findings WHERE report_date >= ?",
            (cutoff,),
        ).fetchall()
    finally:
        db.close()

    counts: dict[str, int] = {}
    for row in rows:
        issue = (row["issue"] or "").lower()
        if not any(key in issue for key in issues):
            continue
        try:
            detail = json.loads(row["detail"] or "{}")
        except json.JSONDecodeError:
            continue
        ip = detail.get("dst_ip")
        if ip:
            counts[ip] = counts.get(ip, 0) + 1
    return counts


def newest_report_date(db_path: Path) -> date | None:
    """Newest report_date in the store, across all report types.

    Deliberately the whole table, not just Badbox rows: this measures whether
    ingest is alive. Badbox events legitimately dropping to zero would be good
    news, not a reason to stop publishing the list.
    """
    db = sqlite3.connect(db_path)
    try:
        row = db.execute("SELECT MAX(report_date) FROM findings").fetchone()
    finally:
        db.close()
    if not row or not row[0]:
        return None
    try:
        return date.fromisoformat(row[0])
    except (TypeError, ValueError):
        return None


def render(
    addresses: dict[str, int],
    list_name: str,
    generated_at: str,
    data_through: date,
    lookback_days: int,
) -> str:
    lines = [
        f"# Generated {generated_at} from Shadowserver data through {data_through}.",
        f"# {len(addresses)} addresses, {lookback_days}-day lookback. Do not edit by hand.",
        f'/ip firewall address-list remove [find list="{list_name}"]',
    ]
    for ip, hits in sorted(addresses.items()):
        lines.append(
            f'/ip firewall address-list add list="{list_name}" '
            f'address={ip} comment="auto: {hits} hits"'
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="data/shadowserver/shadowserver.db")
    ap.add_argument("--out", required=True, help="destination .rsc file")
    ap.add_argument("--days", type=int, default=LOOKBACK_DAYS)
    ap.add_argument("--issues", default=",".join(DEFAULT_ISSUES),
                    help="comma-separated issue substrings to include")
    ap.add_argument("--max-staleness-days", type=int, default=MAX_STALENESS_DAYS,
                    help="refuse if the newest report is older than this")
    args = ap.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"database not found: {db_path}", file=sys.stderr)
        return 1

    newest = newest_report_date(db_path)
    if newest is None:
        print("no report dates in the database -- refusing to write", file=sys.stderr)
        return EXIT_STALE

    age = (datetime.now(timezone.utc).date() - newest).days
    if age > args.max_staleness_days:
        print(
            f"newest report is {newest} ({age} days old, limit "
            f"{args.max_staleness_days}) -- refusing to write. Check that the "
            "hourly ssdash ingest is still running; the router keeps its "
            "current list.",
            file=sys.stderr,
        )
        return EXIT_STALE

    issues = tuple(i.strip().lower() for i in args.issues.split(",") if i.strip())
    addresses = c2_addresses(db_path, args.days, issues)

    if not addresses:
        print(
            f"no matching C2 addresses in the last {args.days} days -- "
            "not writing the list (leaving the router's copy untouched)",
            file=sys.stderr,
        )
        return EXIT_NO_ADDRESSES

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(render(addresses, LIST_NAME, generated_at, newest, args.days))
    tmp.replace(out)  # atomic: a router fetch never sees a half-written file

    print(f"{len(addresses)} addresses -> {out} (data through {newest})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
