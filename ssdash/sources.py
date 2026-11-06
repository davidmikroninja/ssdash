"""Where reports come from. Each source drops plain CSVs into data/raw/<date>/ and
returns a list of (csv_path, source_name, expected_rows_or_None).

  api    - Shadowserver Reports API (preferred once you have a key)
  imap   - the mailbox the report emails land in (zip attachment, falls back to the link)
  folder - any .csv / .csv.zip dropped into the inbox folder (manual / testing)
"""
import email
import hashlib
import hmac
import imaplib
import io
import json
import re
import urllib.request
import zipfile
from datetime import date, timedelta
from email.header import decode_header
from pathlib import Path

from .store import parse_filename

DL_LINK_RE = re.compile(r"https://dl\.shadowserver\.org/[A-Za-z0-9_\-?=&]+")
EVENTS_RE = re.compile(r"contains\s+(\d+)\s+events?", re.I)


def _save_csvs(blob: bytes, name: str, raw_dir: Path) -> list[Path]:
    """Save a .csv or every .csv inside a .zip under raw/<report_date>/."""
    out = []
    if blob[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            members = [(Path(m).name, z.read(m)) for m in z.namelist() if m.lower().endswith(".csv")]
    else:
        members = [(Path(name).name.removesuffix(".zip"), blob)]
    for fname, data in members:
        try:
            report_date, _ = parse_filename(fname)
        except ValueError:
            continue
        dest = raw_dir / report_date / fname
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        out.append(dest)
    return out


def _download(url: str, timeout=60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "ssdash/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# --------------------------------------------------------------------------- API
def _api_call(cfg: dict, method: str, body: dict | None = None):
    """POST <uri><method> with the JSON body signed by HMAC-SHA256 of the secret (header HMAC2).
    Ref: github.com/The-Shadowserver-Foundation/api_utils"""
    uri = cfg.get("uri", "https://transform.shadowserver.org/api2/")
    body = dict(body or {})
    body["apikey"] = cfg["key"]
    payload = json.dumps(body).encode()
    sig = hmac.new(str(cfg["secret"]).encode(), payload, hashlib.sha256).hexdigest()
    req = urllib.request.Request(uri + method, data=payload, headers={"HMAC2": sig})
    with urllib.request.urlopen(req, timeout=60) as r:
        out = json.loads(r.read())
    if isinstance(out, dict) and out.get("error"):
        raise RuntimeError(f"Shadowserver API error: {out['error']}")
    return out


def _api_list(cfg: dict, days: int):
    end = date.today()
    body = {"date": f"{end - timedelta(days=days)}:{end}", "limit": 1000}
    if cfg.get("reports"):
        body["reports"] = cfg["reports"]
    return _api_call(cfg, "reports/list", body)


def fetch_api(cfg: dict, raw_dir: Path, days: int = 3):
    """Reports API: reports/list for the last few days, then download each new file
    from https://dl.shadowserver.org/<id>."""
    results = []
    for item in _api_list(cfg, days):
        fname = item.get("file", "")
        try:
            report_date, _ = parse_filename(fname)
        except ValueError:
            continue
        if (raw_dir / report_date / fname).exists():
            continue  # already downloaded (by API or email)
        blob = _download(f"https://dl.shadowserver.org/{item['id']}")
        for p in _save_csvs(blob, fname, raw_dir):
            results.append((p, "api", None))
    return results


def api_test(cfg: dict, days: int = 7):
    """Read-only check of the API key: ping, list recent reports, download one and count rows.
    Writes nothing to the database."""
    import csv
    from collections import Counter
    print("1. ping ...", end=" ", flush=True)
    print(_api_call(cfg, "test/ping"))
    print(f"2. reports/list for the last {days} days ...", end=" ", flush=True)
    listing = _api_list(cfg, days)
    print(f"{len(listing)} reports")
    if not listing:
        print("   Nothing listed - check the key is linked to the expected report set.")
        return
    by_date = Counter(i.get("timestamp", "?")[:10] for i in listing)
    for d, n in sorted(by_date.items()):
        print(f"   {d}: {n} reports")
    types = sorted({i.get("type") or (parse_filename(i["file"])[1] if i.get("file") else "?") for i in listing})
    print(f"   types: {', '.join(types)}")
    print(f"   report sets: {', '.join(sorted({str(i.get('report')) for i in listing}))}")
    item = sorted(listing, key=lambda i: i.get("timestamp", ""))[-1]
    print(f"3. download {item.get('file')} ...", end=" ", flush=True)
    blob = _download(f"https://dl.shadowserver.org/{item['id']}")
    if blob[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            blob = z.read(z.namelist()[0])
    rows = list(csv.reader(io.StringIO(blob.decode("utf-8-sig", "replace"))))
    print(f"{len(blob)} bytes, {max(len(rows) - 1, 0)} events, columns: {', '.join(rows[0][:6]) if rows else '-'} ...")
    print("API OK - compare the file names above with what arrived by email for the same days.")


# --------------------------------------------------------------------------- IMAP
def _subject(msg) -> str:
    parts = decode_header(msg.get("Subject", ""))
    return "".join(p.decode(c or "utf-8", "replace") if isinstance(p, bytes) else p for p, c in parts)


def _body_text(msg) -> str:
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
    return ""


def fetch_imap(cfg: dict, raw_dir: Path):
    """Read unseen Shadowserver mails, save their CSVs, then mark them seen
    (and optionally move them to a processed folder)."""
    cls = imaplib.IMAP4_SSL if cfg.get("ssl", True) else imaplib.IMAP4
    m = cls(cfg["host"], int(cfg.get("port", 993 if cfg.get("ssl", True) else 143)))
    m.login(cfg["user"], cfg["password"])
    m.select(cfg.get("folder", "INBOX"))
    sender = cfg.get("from_filter", "shadowserver.org")
    typ, data = m.search(None, "UNSEEN", "FROM", f'"{sender}"')
    results = []
    for num in data[0].split():
        _, msg_data = m.fetch(num, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])
        text = _body_text(msg)
        em = EVENTS_RE.search(text)
        expected = int(em.group(1)) if em else None

        saved = []
        for part in msg.walk():
            fname = part.get_filename()
            if fname and (fname.lower().endswith(".zip") or fname.lower().endswith(".csv")):
                saved += _save_csvs(part.get_payload(decode=True), fname, raw_dir)
        if not saved:  # no attachment -> use the download link
            link = DL_LINK_RE.search(text)
            if link:
                # filename isn't in the URL; take it from the subject/body if present
                fm = re.search(r"\d{4}-\d{2}-\d{2}-[A-Za-z0-9_]+-[^\s]+?\.csv", text + " " + _subject(msg))
                saved += _save_csvs(_download(link.group(0)), fm.group(0) if fm else "unknown.csv", raw_dir)

        results += [(p, "imap", expected if len(saved) == 1 else None) for p in saved]
        if saved:
            m.store(num, "+FLAGS", "\\Seen")
            if cfg.get("move_to"):
                m.copy(num, cfg["move_to"])
                m.store(num, "+FLAGS", "\\Deleted")
        else:
            m.store(num, "-FLAGS", "\\Seen")  # leave it for a human to look at
    if cfg.get("move_to"):
        m.expunge()
    m.logout()
    return results


# --------------------------------------------------------------------------- folder
def fetch_folder(cfg: dict, raw_dir: Path):
    inbox = Path(cfg.get("path", "data/inbox"))
    inbox.mkdir(parents=True, exist_ok=True)
    results = []
    for f in sorted(inbox.iterdir()):
        if f.suffix.lower() in (".zip", ".csv"):
            results += [(p, "folder", None) for p in _save_csvs(f.read_bytes(), f.name, raw_dir)]
            done = inbox / "processed"
            done.mkdir(exist_ok=True)
            f.replace(done / f.name)
    return results


SOURCES = {"api": fetch_api, "imap": fetch_imap, "folder": fetch_folder}
