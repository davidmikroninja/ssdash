"""Build the self-contained HTML dashboard (no external assets - works offline/intranet)."""
import json
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from .catalog import CATEGORY_ORDER, SEV_RANK, describe

TEMPLATE = Path(__file__).with_name("template.html")


def build(store, out_path, label="Shadowserver", history_days=90, severity_overrides=None, customers=None):
    since = (date.today() - timedelta(days=history_days)).isoformat()
    findings = store.findings(since)
    files = store.files(since)
    types = {}
    for f in findings:
        if f["base_type"] not in types:
            d = describe(f["report_type"])
            types[f["base_type"]] = {k: d[k] for k in ("title", "category", "guidance")}
    overrides = severity_overrides or {}
    for f in findings:
        f.pop("id", None)  # not needed by the page
        # local policy: raise (never lower) Shadowserver's rating for chosen report types
        want = overrides.get(f["base_type"])
        if want in SEV_RANK and SEV_RANK[want] < SEV_RANK[f["severity"]]:
            f["sev_original"] = f["severity"]
            f["severity"] = want
        info = customers.lookup(f["ip"]) if customers else None
        f["customer"] = info["customer"] if info else ""
        f["cust_state"] = "named" if info and info["customer"] else ("blank" if info else "missing")
        extra = {k: v for k, v in (info or {}).items() if k not in ("customer", "blank")}
        if extra:
            f["cust_info"] = extra
    data = {
        "label": label,
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "categories": CATEGORY_ORDER,
        "types": types,
        "findings": findings,
        "files": files,
        "has_customers": bool(customers and customers.entries),
    }
    # Safe to embed inside <script type="application/json">: escape anything that could close the tag
    blob = json.dumps(data, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    html = TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", blob)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Unique temp name: the hourly cron build and a manual rebuild
    # can run at the same time, and a fixed .tmp path would let them corrupt
    # each other's output.
    tmp = out.with_name(f".{out.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(html, encoding="utf-8")
    tmp.replace(out)  # atomic swap so the web server never serves a half-written file
    return out
