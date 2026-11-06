"""SQLite store + CSV normaliser.

Every Shadowserver CSV, whatever its report type, is flattened into one `findings`
table with a common set of columns. Anything report-specific goes into `detail`
(JSON of the non-empty extra columns), so nothing is lost.
"""
import csv
import hashlib
import io
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .catalog import SEVERITIES, describe

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    filename      TEXT PRIMARY KEY,
    sha256        TEXT NOT NULL,
    report_date   TEXT NOT NULL,
    report_type   TEXT NOT NULL,
    rows          INTEGER NOT NULL,
    expected_rows INTEGER,          -- from the API listing / email body, if known
    source        TEXT,             -- api | imap | folder
    ingested_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS findings (
    id          INTEGER PRIMARY KEY,
    report_date TEXT NOT NULL,
    report_type TEXT NOT NULL,
    base_type   TEXT NOT NULL,
    category    TEXT NOT NULL,
    ts          TEXT,
    severity    TEXT NOT NULL,
    ip          TEXT NOT NULL,
    family      TEXT NOT NULL,
    port        TEXT,
    protocol    TEXT,
    hostname    TEXT,
    issue       TEXT,
    detail      TEXT,
    filename    TEXT NOT NULL,
    UNIQUE (report_type, ts, ip, port, issue)
);
CREATE INDEX IF NOT EXISTS ix_findings_date ON findings(report_date);
CREATE INDEX IF NOT EXISTS ix_findings_ip   ON findings(ip);
"""

# Columns that are the same for every row in an ASN feed - kept out of `detail`
COMMON = {"timestamp", "severity", "ip", "src_ip", "protocol", "port", "src_port", "hostname",
          "src_hostname", "asn", "src_asn", "geo", "src_geo", "region", "src_region", "city",
          "src_city", "naics", "src_naics", "sector", "src_sector", "hostname_source"}

FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-([A-Za-z0-9_]+)-")


def parse_filename(name: str):
    """'2026-10-08-scan_ntp-10591-example-asn.csv' -> ('2026-10-08', 'scan_ntp')"""
    m = FILENAME_RE.match(Path(name).name)
    if not m:
        raise ValueError(f"Unrecognised Shadowserver filename: {name}")
    return m.group(1), m.group(2)


def _issue(base: str, r: dict) -> str:
    """One short human label for what was found."""
    if base.startswith("event_"):
        return r.get("infection") or r.get("tag") or base
    if base.startswith("blocklist"):
        reason = r.get("reason")
        src = r.get("source") or "blocklist"
        return src if not reason or reason == "not-specified" else f"{src} ({reason})"
    if base == "device_id":
        parts = [r.get("device_vendor"), r.get("device_type"), r.get("device_model")]
        return " ".join(p for p in parts if p) or r.get("tag") or "device"
    return r.get("tag") or base


def _port(base: str, r: dict) -> str:
    if base.startswith("event_"):
        # for attack events the interesting port is the service being attacked
        return r.get("dst_port") or ""
    return r.get("port") or ""


def normalise(text: str, filename: str):
    report_date, report_type = parse_filename(filename)
    meta = describe(report_type)
    base = meta["base_type"]
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        r = {k: (v or "").strip() for k, v in r.items() if k}
        ip = r.get("ip") or r.get("src_ip")
        if not ip:
            continue
        sev = (r.get("severity") or "").lower()
        if sev not in SEVERITIES:
            sev = "info" if meta["category"].startswith("Inventory") else "medium"
        detail = {k: v for k, v in r.items() if v and k not in COMMON}
        out.append({
            "report_date": report_date,
            "report_type": report_type,
            "base_type": base,
            "category": meta["category"],
            "ts": r.get("timestamp", ""),
            "severity": sev,
            "ip": ip,
            "family": "IPv6" if ":" in ip else "IPv4",
            "port": _port(base, r),
            "protocol": r.get("protocol", ""),
            "hostname": r.get("hostname") or r.get("src_hostname") or "",
            "issue": _issue(base, r),
            "detail": json.dumps(detail, separators=(",", ":")),
            "filename": Path(filename).name,
        })
    return report_date, report_type, out


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def ingest_file(self, csv_path: Path, source="folder", expected_rows=None) -> int | None:
        """Load one CSV. Returns rows loaded, or None if this exact file was already loaded."""
        data = Path(csv_path).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        name = Path(csv_path).name
        row = self.db.execute("SELECT sha256 FROM files WHERE filename=?", (name,)).fetchone()
        if row and row["sha256"] == digest:
            return None
        report_date, report_type, rows = normalise(data.decode("utf-8-sig", errors="replace"), name)
        with self.db:
            self.db.execute("DELETE FROM findings WHERE filename=?", (name,))
            self.db.executemany(
                "INSERT OR IGNORE INTO findings (report_date, report_type, base_type, category, ts, "
                "severity, ip, family, port, protocol, hostname, issue, detail, filename) VALUES "
                "(:report_date,:report_type,:base_type,:category,:ts,:severity,:ip,:family,:port,"
                ":protocol,:hostname,:issue,:detail,:filename)", rows)
            self.db.execute(
                "INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?,?)",
                (name, digest, report_date, report_type, len(rows), expected_rows, source,
                 datetime.now(timezone.utc).isoformat(timespec="seconds")))
        return len(rows)

    def findings(self, since: str):
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM findings WHERE report_date >= ? ORDER BY report_date, ts", (since,))]

    def findings_for_file(self, filename: str):
        return [dict(r) for r in self.db.execute("SELECT * FROM findings WHERE filename=?", (filename,))]

    def files(self, since: str):
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM files WHERE report_date >= ? ORDER BY report_date DESC, report_type", (since,))]
