# Shadowserver dashboard (ssdash)

Ingests Shadowserver reports for your own announced address space — from the
Reports API, an IMAP mailbox, or a local folder — and publishes a single
self-contained HTML dashboard. Nothing is probed: every finding comes from
Shadowserver's own scans.

For installation, the full configuration reference, dashboard operation and
troubleshooting, see the [operator manual](../docs/manual.md).

- **Management:** severity tiles, actionable-events trend, counts by report type.
- **NOC:** an action list with one row per IP and issue, worst first, showing first and last
  seen and New / Ongoing / Not in latest report status. Clicking a row shows what to do and
  the raw fields.
- **Inventory:** informational feeds (device ID, IKE population, etc.) kept out of the way.
- **Ingestion log:** every file loaded, with the email's event count checked against the rows loaded.

The dashboard uses only the Python standard library (Python 3.11 or later;
`openpyxl` is needed for `.xlsx` customer sheets).

## How it works

```
 Reports API ─┐
 IMAP mailbox ├─► data/shadowserver/raw/<date>/*.csv ─► SQLite ─► public/shadowserver/index.html
 inbox folder ┘
```

* **Sources** are tried in the order given in `config/shadowserver.toml`. The same file
  arriving from both the API and email is only loaded once, because files are de-duplicated
  by name and SHA-256.
* **IMAP** reads unseen mail from `shadowserver.org`, unzips the attached CSV, and falls back
  to the `dl.shadowserver.org` link if there is no attachment. The "contains N events" line is
  recorded and compared with the rows actually loaded.
* **API** calls `reports/list` for the last 3 days, signing the request with HMAC-SHA256 in the
  `HMAC2` header, then downloads each file from `https://dl.shadowserver.org/<id>`.
* **Unknown report types** are still loaded. `ssdash/catalog.py` guesses the category from
  the type's prefix. Add an entry there for a proper title and remediation text.
* **IPv6 variants** (`scan6_*`, `device_id6`, `event6_*`) fold into the same row of the
  report-type table as their IPv4 counterparts.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt        # openpyxl, only for .xlsx customer sheets
cp config/shadowserver.example.toml config/shadowserver.toml   # fill in API key / IMAP / relay details
.venv/bin/python -m ssdash -c config/shadowserver.toml apitest # check the key, read-only, writes nothing
.venv/bin/python -m ssdash -c config/shadowserver.toml run     # fetch + ingest + build
```

Run these from the repository root so `ssdash` is importable. `apitest` pings the API, lists
reports from the last 7 days (`--days` to change), and downloads the newest one to count its
events — all read-only, nothing is written to the database. Run it from a host that can
actually reach the internet; Shadowserver may be unreachable from a sandboxed dev machine.
Compare the report types it lists against what's already arriving by email for the same days.

Manual load (e.g. backfilling old emails):

```bash
.venv/bin/python -m ssdash -c config/shadowserver.toml ingest ~/Downloads/2026-10-*.csv.zip
```

### Schedule it

Shadowserver publishes reports through the day, so run it hourly:

```cron
15 * * * *  cd /path/to/ssdash && .venv/bin/python -m ssdash -c config/shadowserver.toml run >> /var/log/ssdash.log 2>&1
```

### Serve it

The configured `output` path is a single static file with no external requests. Point nginx
(or any web server) at its directory and put it behind your own authentication. The page
contains customer IPs and names, so keep it internal.

## Customer mapping

Set `customers_file` in `config/shadowserver.toml` to the public IP assignment sheet (.csv, or
.xlsx with `openpyxl` installed). Columns are matched by header name: an address column
(single IP, CIDR, or `a.b.c.d - a.b.c.e` range, or separate start/end columns) and a customer
column. Optional account, service, site, contact and notes columns are shown in the detail
panel. Matching is longest-prefix, so a customer's /29 inside a pool /22 resolves to the
customer. The sheet is re-read on every build. IPs not in the sheet are flagged "Not in IP sheet".

## Severity

Ratings come from Shadowserver's `severity` column. `[severity_overrides]` in the config can
**raise** a report type's rating; it never lowers one. The example raises
`scan_mikrotik_service` (exposed btest/Winbox, rated `info` by Shadowserver) to `medium`, so
those routers appear in the action list. Raised rows say so in their detail panel.

## Files

| Path | What |
|---|---|
| `ssdash/catalog.py` | Report-type titles, categories, remediation text |
| `ssdash/store.py` | CSV → common schema, SQLite store |
| `ssdash/sources.py` | API, IMAP and folder collectors |
| `ssdash/customers.py` | IP → customer mapping from the assignment sheet |
| `ssdash/render.py` + `ssdash/template.html` | Dashboard builder |
| `ssdash/__main__.py` | CLI and digest email |
