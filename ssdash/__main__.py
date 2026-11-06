"""ssdash - Shadowserver report summariser.

    python -m ssdash run     [-c config/shadowserver.toml]   fetch + ingest + build (+ digest)  <- cron this
    python -m ssdash ingest  PATH...            load .csv / .csv.zip files by hand
    python -m ssdash build                      rebuild the dashboard only
    python -m ssdash apitest [--days 7]         check the API key (read-only)
"""
import argparse
import smtplib
import sys
import tomllib
from collections import Counter
from email.message import EmailMessage
from pathlib import Path

from .catalog import SEV_RANK
from .customers import CustomerMap
from .render import build
from .sources import SOURCES, _save_csvs, api_test
from .store import Store


def load_config(path):
    p = Path(path)
    if not p.exists():
        sys.exit(f"Config not found: {p} (copy config/shadowserver.example.toml to config/shadowserver.toml)")
    return tomllib.loads(p.read_text())


def send_digest(cfg, store, new_rows):
    d = cfg.get("digest", {})
    if not d.get("enabled") or not new_rows:
        return
    actionable = [r for r in new_rows if r["severity"] != "info"]
    sev = Counter(r["severity"] for r in actionable)
    lines = [f"Shadowserver: {len(new_rows)} new events loaded, {len(actionable)} actionable.", ""]
    for s in ["critical", "high", "medium", "low"]:
        if sev[s]:
            lines.append(f"  {s.capitalize():9} {sev[s]}")
    worst = sorted(actionable, key=lambda r: (SEV_RANK[r["severity"]], r["ip"]))[:15]
    if worst:
        lines += ["", "Top items:"]
        lines += [f"  [{r['severity']}] {r['ip']:<18} {r['issue']} ({r['report_type']})" for r in worst]
    if d.get("dashboard_url"):
        lines += ["", f"Dashboard: {d['dashboard_url']}"]
    msg = EmailMessage()
    msg["Subject"] = f"Shadowserver digest: {sev['critical']} critical, {sev['high']} high, {len(actionable)} actionable"
    msg["From"] = d["from"]
    msg["To"] = ", ".join(d["to"])
    msg.set_content("\n".join(lines))
    with smtplib.SMTP(d.get("smtp_host", "localhost"), int(d.get("smtp_port", 25))) as s:
        if d.get("starttls"):
            s.starttls()
        if d.get("smtp_user"):
            s.login(d["smtp_user"], d["smtp_password"])
        s.send_message(msg)


def ingest_paths(store, paths, raw_dir):
    for p in map(Path, paths):
        for c in _save_csvs(p.read_bytes(), p.name, raw_dir):
            n = store.ingest_file(c, source="manual")
            print(f"  skip (already loaded)  {c.name}" if n is None else f"  loaded {n:>5} rows     {c.name}")


def main():
    ap = argparse.ArgumentParser(prog="ssdash")
    ap.add_argument("-c", "--config", default="config.toml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run")
    sub.add_parser("build")
    t = sub.add_parser("apitest", help="check the Shadowserver API key (read-only)")
    t.add_argument("--days", type=int, default=7)
    ing = sub.add_parser("ingest")
    ing.add_argument("paths", nargs="+")
    a = ap.parse_args()

    cfg = load_config(a.config)
    if a.cmd == "apitest":
        try:
            api_test(cfg.get("api", {}), a.days)
        except Exception as e:
            sys.exit(f"API test failed: {e}")
        return
    data_dir = Path(cfg.get("data_dir", "data"))
    raw_dir = data_dir / "raw"
    store = Store(data_dir / "shadowserver.db")
    out = cfg.get("output", "public/index.html")
    label = cfg.get("label", "Shadowserver")

    if a.cmd == "ingest":
        ingest_paths(store, a.paths, raw_dir)
    elif a.cmd == "run":
        new_rows = []
        for name in cfg.get("sources", ["folder"]):
            print(f"[{name}]")
            try:
                got = SOURCES[name](cfg.get(name, {}), raw_dir)
            except Exception as e:  # one broken source shouldn't stop the others
                print(f"  ERROR: {e}", file=sys.stderr)
                continue
            for path, src, expected in got:
                n = store.ingest_file(path, source=src, expected_rows=expected)
                if n is not None:
                    print(f"  loaded {n:>5} rows     {path.name}")
                    new_rows += store.findings_for_file(path.name)
        try:
            send_digest(cfg, store, new_rows)
        except Exception as e:
            print(f"  digest ERROR: {e}", file=sys.stderr)

    customers = None
    if cfg.get("customers_file"):
        customers = CustomerMap(cfg["customers_file"], cfg.get("customers_sheets"))
        print(f"customers: {len(customers.entries)} named + {len(customers.blank)} blank entries from {cfg['customers_file']}")
        for p in customers.problems[:20]:
            print(f"  customer sheet: {p}", file=sys.stderr)
    path = build(store, out, label=label, history_days=int(cfg.get("history_days", 90)),
                 severity_overrides=cfg.get("severity_overrides", {}), customers=customers)
    print(f"dashboard -> {path}")


if __name__ == "__main__":
    main()
