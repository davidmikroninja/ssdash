# ssdash operator manual

This is the full operating manual for the two tools in this repository:

- **`ssdash/`** — ingests Shadowserver reports for your announced address
  space and builds a static HTML dashboard. It never probes anything; every
  finding comes from Shadowserver's own scans.
- **`deploy/badbox/`** — converts BadBox/Vo1d sinkhole events from the ssdash
  database into a RouterOS address list, and installs router rules that
  detect and quarantine infected CPEs.

Unless a step says otherwise, run commands from the repository root so the
`ssdash` package is importable.

## Contents

- [Getting Shadowserver access](#getting-shadowserver-access)

1. [Architecture](#1-architecture)
2. [Requirements](#2-requirements)
3. [Installation](#3-installation)
4. [Configuration reference](#4-configuration-reference)
5. [First run](#5-first-run)
6. [Scheduling](#6-scheduling)
7. [Using the dashboard](#7-using-the-dashboard)
8. [Customer mapping](#8-customer-mapping)
9. [Severity and overrides](#9-severity-and-overrides)
10. [Digest email](#10-digest-email)
11. [Data, backup and retention](#11-data-backup-and-retention)
12. [BadBox containment](#12-badbox-containment)
13. [Troubleshooting](#13-troubleshooting)
14. [Security hardening](#14-security-hardening)
15. [Command reference](#15-command-reference)
16. [File layout](#16-file-layout)

---

## Getting Shadowserver access

ssdash consumes reports that Shadowserver provides free to network owners
and national CSIRTs for the networks they control. The subscription and API
credentials come from Shadowserver; this repository does not create or
bypass them.

1. **Check the scope.** Read the
   [network reporting overview](https://www.shadowserver.org/what-we-do/network-reporting/).
   Reports are for your own network or constituency. You can list ASNs you
   control completely, CIDR blocks, domain space, or — for a national CSIRT —
   the country you represent. An ISP's ASN is not accepted unless you are
   that ISP or list only your allocation.
2. **Subscribe.** Complete the
   [Subscribe to Reports](https://www.shadowserver.org/what-we-do/network-reporting/get-reports/)
   form with:
   - your name, organisation, role, email and phone number;
   - the ASNs or CIDRs you control;
   - the report recipient address(es);
   - references — ideally people listed in whois for the network space.
3. **Request API access.** In the form's References section, ask for API
   access. If you have already subscribed, use the
   [contact form](https://www.shadowserver.org/contact/) and request it.
   Shadowserver delivers reports by email by default; the API is recommended
   for automation.
4. **Receive credentials.** Shadowserver vets the request and follows up,
   possibly with questions. Once approved it issues the API key and secret,
   scoped to your subscribed network. Do not share them or commit
   `config/shadowserver.toml`.
5. **Configure ssdash.** Put the key and secret in `[api]` (`key` and
   `secret`), optionally limit the report sets with `reports`, then run:

   ```sh
   .venv/bin/python -m ssdash -c config/shadowserver.toml apitest
   ```

   If you receive reports by email instead of the API, configure `[imap]`;
   `run` will collect from the mailbox.

Official references: [Shadowserver](https://www.shadowserver.org/),
[network reporting](https://www.shadowserver.org/what-we-do/network-reporting/),
[Subscribe to Reports](https://www.shadowserver.org/what-we-do/network-reporting/get-reports/),
[API documentation](https://www.shadowserver.org/what-we-do/network-reporting/api-documentation/),
[API utils wiki](https://github.com/The-Shadowserver-Foundation/api_utils/wiki),
and the [contact form](https://www.shadowserver.org/contact/).

---

## 1. Architecture

```
 Shadowserver Reports API ─┐
 IMAP mailbox ─────────────┼─► data/shadowserver/raw/<date>/*.csv
 local inbox folder ───────┘              │
                                          ▼
                                   data/shadowserver/shadowserver.db
                                     │                    │
                                     ▼                    ▼
                        public/shadowserver/     deploy/badbox/
                             index.html          badbox_c2.rsc
                        (static dashboard)             │
                                                       ▼
                                              RouterOS access router
                                              /tool fetch + /import
```

Two independent outputs come from the same SQLite store:

1. **The dashboard** — a single self-contained HTML file with no external
   assets or server-side code.
2. **The BadBox address list** — a RouterOS import file that replaces the
   `Dynamic_BadBox_C2` address list on routers that fetch it.

The only components that talk to Shadowserver are the API and IMAP
collectors. Nothing in this repository scans or probes your network.

## 2. Requirements

| Component | Requirement |
|---|---|
| Host | Linux, macOS, or any OS with Python 3.11+ |
| Python | 3.11 or later (`tomllib` is required) |
| Python packages | none for the core; `openpyxl` only for `.xlsx` customer sheets |
| Storage | local filesystem; SQLite is embedded |
| Web server | optional, for serving the dashboard and the BadBox list |
| Routers | RouterOS 7.x for the BadBox scripts |

The host must be able to reach the Shadowserver API and/or your IMAP server.
If it cannot, run ssdash on a host that can and copy the generated files to
where they are served.

## 3. Installation

```sh
git clone https://github.com/davidmikroninja/ssdash.git
cd ssdash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`requirements.txt` installs `openpyxl`; it is optional and only used when
`customers_file` is an `.xlsx` or `.xlsm` workbook. The dashboard and the
BadBox generator otherwise use only the standard library.

Check the installation:

```sh
.venv/bin/python -m ssdash --help
.venv/bin/python deploy/badbox/generate_c2_list.py --help
```

If you need to run the tools from outside the repository root, either change
to the root first (recommended, especially in cron) or set
`PYTHONPATH=/path/to/ssdash`.

## 4. Configuration reference

Create the working configuration from the example:

```sh
cp config/shadowserver.example.toml config/shadowserver.toml
chmod 600 config/shadowserver.toml
```

`config/shadowserver.toml` holds API keys and mail credentials. It is
git-ignored; keep it out of version control and readable only by the service
user.

All keys are optional unless marked **required**. Defaults apply when a key
is omitted.

### 4.1 Top-level keys

| Key | Default | Meaning |
|---|---|---|
| `label` | `"Shadowserver"` | Text shown in the dashboard header and subtitle |
| `data_dir` | `"data"` | Root directory for the SQLite database and raw CSV archive |
| `output` | `"public/index.html"` | Path of the generated dashboard file |
| `history_days` | `90` | How many days of findings the dashboard includes |
| `customers_file` | none | IP assignment sheet (`.csv`, `.xlsx` or `.xlsm`) |
| `customers_sheets` | all sheets | Workbook tabs to read, e.g. `["IPv4", "IPv6"]` |
| `sources` | `["folder"]` | Source collectors to try, in order |

The example config uses `data_dir = "data/shadowserver"` and
`output = "public/shadowserver/index.html"`; adjust these to match your
deployment.

### 4.2 `[api]` — Shadowserver Reports API

| Key | Default | Meaning |
|---|---|---|
| `key` | **required** | API key issued by Shadowserver |
| `secret` | **required** | API secret paired with the key |
| `uri` | `https://transform.shadowserver.org/api2/` | API base URL |
| `reports` | none | Optional list of report-set names to request |

The API collector asks for the last 3 days of reports on each run and
downloads new files from `https://dl.shadowserver.org/`. It signs requests
with HMAC-SHA256 in the `HMAC2` header. See
[Getting Shadowserver access](#getting-shadowserver-access) for how to
obtain the key and secret.

### 4.3 `[imap]` — mailbox collector

| Key | Default | Meaning |
|---|---|---|
| `host` | **required** | IMAP server hostname |
| `port` | `993` with SSL, otherwise `143` | IMAP port |
| `ssl` | `true` | Use IMAPS |
| `user` | **required** | Mailbox login |
| `password` | **required** | Mailbox password or app password |
| `folder` | `"INBOX"` | Mailbox folder to read |
| `from_filter` | `"shadowserver.org"` | Sender filter for the IMAP search |
| `move_to` | none | Optional folder to move processed mail into |

The collector reads **unseen** mail from the configured sender, saves the
attached `.csv`/`.zip`, and marks a message seen only when at least one CSV
was saved. If there is no attachment it tries the `dl.shadowserver.org` link
in the body. A message with neither is left unseen for a human to inspect.
Email delivery is the default if you do not request API access; see
[Getting Shadowserver access](#getting-shadowserver-access).

### 4.4 `[folder]` — manual inbox

| Key | Default | Meaning |
|---|---|---|
| `path` | `"data/inbox"` | Directory scanned for `.csv` / `.csv.zip` files |

Files are loaded, then moved into `<path>/processed/`. This source is useful
for testing and for backfilling files by hand.

### 4.5 `[digest]` — email summary

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Send a digest after a run that loaded new rows |
| `smtp_host` | `"localhost"` | SMTP relay hostname |
| `smtp_port` | `25` | SMTP port |
| `starttls` | `false` | Issue STARTTLS before sending |
| `smtp_user` | none | SMTP username, if the relay requires login |
| `smtp_password` | none | SMTP password |
| `from` | **required when enabled** | Envelope/header sender |
| `to` | **required when enabled** | List of recipient addresses |
| `dashboard_url` | none | Optional link included at the end of the digest |

The digest is only sent by the `run` command, only when `enabled = true`,
and only when that run actually loaded new rows. Manual `ingest` does not
send a digest. A digest failure is printed to stderr but does not stop the
dashboard build.

### 4.6 `[severity_overrides]`

See [Severity and overrides](#9-severity-and-overrides).

### 4.7 Minimal test configuration

A folder-only configuration that needs no network access and no credentials:

```toml
label = "Shadowserver"
data_dir = "data/shadowserver"
output = "public/shadowserver/index.html"
sources = ["folder"]

[folder]
path = "data/shadowserver/inbox"
```

Drop a correctly named CSV (see [Manual ingest](#54-manual-ingest)) into
`data/shadowserver/inbox/` and run `ssdash run`.

## 5. First run

### 5.1 Check the API key

```sh
.venv/bin/python -m ssdash -c config/shadowserver.toml apitest
```

`apitest` is read-only. It performs three steps:

1. Calls `test/ping`.
2. Lists reports from the last 7 days (`--days N` to change).
3. Downloads the newest report and counts its events.

Nothing is written to the database. Run it from a host that can reach the
internet. If it lists no reports, check that the key is linked to the correct
report set and, if you set `[api] reports`, that the name matches.

### 5.2 Fetch, ingest and build

```sh
.venv/bin/python -m ssdash -c config/shadowserver.toml run
```

For each configured source, in order, `run`:

- fetches new report files;
- de-duplicates them by filename and SHA-256;
- loads new rows into SQLite;
- records the expected row count when the source provides one;
- sends the digest if enabled;
- rebuilds the dashboard.

A failure in one source is printed and does not stop the other sources or
the dashboard build.

Expected output resembles:

```
[api]
  loaded    42 rows     2026-11-05-scan_ntp-10591-example-asn.csv
[imap]
customers: 120 named + 4 blank entries from customers.csv
dashboard -> public/shadowserver/index.html
```

### 5.3 Build only

```sh
.venv/bin/python -m ssdash -c config/shadowserver.toml build
```

Rebuilds the dashboard from the existing database. Use this after changing
`label`, `history_days`, severity overrides or the customer sheet; no
fetching or ingestion occurs.

### 5.4 Manual ingest

```sh
.venv/bin/python -m ssdash -c config/shadowserver.toml ingest PATH...
```

Accepts one or more `.csv` or `.csv.zip` files. Filenames must match
Shadowserver's pattern:

```
YYYY-MM-DD-<report_type>-<id>-<report_set>.csv
```

For example:

```
2026-10-08-scan_ntp-10591-example-asn.csv
```

Files whose names do not match are skipped silently. Files already loaded
with the same name and SHA-256 are skipped with a message. A changed file
with the same name replaces that file's findings in the database.

### 5.5 Rebuilding from raw files

The raw CSV archive under `data_dir/raw/` is independent of the database. If
the database is lost, re-ingest the archive:

```sh
find data/shadowserver/raw -name '*.csv' -print0 |
  xargs -0 .venv/bin/python -m ssdash -c config/shadowserver.toml ingest
```

Then rebuild:

```sh
.venv/bin/python -m ssdash -c config/shadowserver.toml build
```

## 6. Scheduling

Run `ssdash run` hourly. Shadowserver publishes reports through the day, and
the BadBox generator expects a reasonably fresh database.

### 6.1 cron

```cron
15 * * * * cd /opt/ssdash && .venv/bin/python -m ssdash -c config/shadowserver.toml run >> /var/log/ssdash.log 2>&1
```

Use absolute paths. If `run` fails repeatedly, the dashboard and the BadBox
list stop advancing; monitor the log or use a process supervisor.

### 6.2 systemd timer

`/etc/systemd/system/ssdash.service`:

```ini
[Unit]
Description=ssdash Shadowserver ingest
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=ssdash
WorkingDirectory=/opt/ssdash
ExecStart=/opt/ssdash/.venv/bin/python -m ssdash -c config/shadowserver.toml run
```

`/etc/systemd/system/ssdash.timer`:

```ini
[Unit]
Description=Run ssdash hourly

[Timer]
OnCalendar=hourly
Persistent=true
RandomizedDelaySec=5m

[Install]
WantedBy=timers.target
```

Enable it:

Create the unprivileged service user (or replace `User=ssdash` with your
own), then enable the timer:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now ssdash.timer
```

Logs go to the journal: `journalctl -u ssdash.service`.

## 7. Using the dashboard

The dashboard is a single static HTML file. Open it directly in a browser,
or serve it with any web server. It contains no external scripts, fonts or
telemetry.

The page reads its data from a JSON block embedded at build time. It only
refreshes when `run` or `build` regenerates the file.

### 7.1 Period selector

| Button | Meaning |
|---|---|
| **Latest day** | Only the newest report date in the data |
| **7 days** | Newest report date and the six days before it |
| **30 days** | Newest report date and the 29 days before it |
| **All** | Every report date included by the build (`history_days`) |

The selection is remembered per browser. All ranges are anchored to the
newest report date in the database, not to today, so a stalled ingest is
visible rather than silently showing an empty dashboard.

### 7.2 Summary tiles

Each severity tile shows two numbers:

- **issues** — one per IP + base report type + issue, aggregated across the period;
- **events** — individual report rows.

The final tile, **IPs needing action**, counts unique IPs with at least one
non-informational issue in the period, and how many of those issues are new.

### 7.3 Charts and tables

- **Actionable events per report day** — stacked bars by severity. Hover a
  day for the per-severity breakdown. Informational reports are excluded.
- **By report type** — grouped by category, with the worst severity, number
  of IPs, event count, last report date, and the raw report-type variants
  that were folded together (for example `scan6_ntp` with `scan_ntp`).
- **Customers affected** — appears only when a customer sheet is configured
  and contains named entries. Shows actionable issues only. Click a customer
  to filter the action list to that customer.

### 7.4 Action list

One row per IP + base report type + issue, worst first. Filters:

| Control | Effect |
|---|---|
| Severity | Minimum severity; choose **Everything incl. info** to include inventory rows |
| Category | Restrict to Compromised, Blocklisted, Exposed, or Inventory |
| Search | Matches IP, customer label, hostname, issue, and report type |

The counter shows both matching rows and unique IPs.

Click a row to expand it. The detail panel shows:

- a **What to do** guidance string for that report type;
- the latest event timestamp, protocol, and number of report days;
- the customer assignment fields, if a customer sheet matched;
- the raw non-common CSV fields for that row.

Status column:

| Status | Meaning |
|---|---|
| **New** | First seen within the selected period |
| **Ongoing** | Seen in the latest report date for this base report type |
| **Not in latest report** | Seen earlier, but absent from the latest report for this base type |

Status is per base report type, so a device can be "Ongoing" for one feed
and "Not in latest report" for another.

### 7.5 Inventory

The collapsible **Inventory** section holds informational reports such as
device identification and IKE responders. These are not vulnerabilities on
their own, but they show what Shadowserver can see and often explain a
matching exposed-service finding. Up to 50 IPs are listed per report type.

### 7.6 Ingestion log

The collapsible **Ingestion log** lists every report file loaded, with its
report date, source (`api`, `imap`, or `manual`), rows loaded, expected rows,
and ingestion timestamp.

- **Expected** is known only for some sources, notably the email's
  "contains N events" line.
- A mismatch is flagged with a warning. It usually means the attachment was
  truncated or the email text disagrees with the CSV; inspect the file and
  re-ingest it if needed.

### 7.7 If the dashboard is empty

Check, in order:

1. `data_dir/shadowserver.db` exists and has findings.
2. The report dates fall inside `history_days`.
3. The period selector is not on **Latest day** with an old newest date.
4. The severity filter is not hiding the rows you expect (info-only reports
   require **Everything incl. info**).

## 8. Customer mapping

Set `customers_file` to a CSV or workbook that maps public IPs to customers.
The file is re-read on every build, so editing it changes the dashboard's
history on the next rebuild without re-ingesting reports.

### 8.1 Header-based CSV

The simplest format is a table with an address column and a customer column:

```csv
cidr,customer,service,site
192.0.2.0/24,Example Customer,Fibre,Site A
198.51.100.10/32,Another Customer,Wireless,Site B
203.0.113.0-203.0.113.255,Range Customer,,
```

Supported columns, matched by header name (case-insensitive, underscores
treated as spaces):

| Purpose | Recognised headers |
|---|---|
| Address | `cidr`, `prefix`, `subnet`, `network`, `ip address`, `ip`, `address`, `block`, `range`, `ip range`, `public ip` |
| Start of range | `start`, `start ip`, `from`, `first ip` |
| End of range | `end`, `end ip`, `to`, `last ip` |
| Customer | `customer`, `customer name`, `client`, `client name`, `company`, `name`, `account name`, `account` |
| Account | `account no`, `account number`, `customer id`, `client id`, `acc no`, `code` |
| Service | `service`, `product`, `package` |
| Site | `site`, `location`, `pop`, `tower` |
| Contact | `contact`, `email`, `contact email` |
| Notes | `notes`, `comment`, `comments`, `description` |

A header row is detected within the first 20 rows when it contains an address
column (or a start column) and a customer column. Rows with malformed
addresses are reported to stderr and skipped. Extra columns are shown in the
action detail panel.

### 8.2 Address forms

The address column accepts:

- a single IP: `192.0.2.10`
- a CIDR: `192.0.2.0/24`
- a range: `192.0.2.10 - 192.0.2.20`
- a shorthand range: `192.0.2.10-20` (expands to `192.0.2.20`)

Ranges are converted to the smallest set of covering networks. Separate
start/end columns are also supported.

### 8.3 Excel workbooks and multiple tabs

`.xlsx` and `.xlsm` files require `openpyxl`. Use `customers_sheets` to read
only named tabs:

```toml
customers_file = "customers.xlsx"
customers_sheets = ["IPv4", "IPv6"]
```

Omit `customers_sheets` to read every tab. Missing requested tabs are
reported on stderr as `customer sheet: sheet not found: ...`.

### 8.4 Grid layout

A tab with no recognised header row is read as a grid: every cell containing
an IP or CIDR takes its label from the cell immediately to its right. Blank
labels are recorded separately and used only when no named entry matches.

This handles sheets laid out as columns of addresses with customer names in
the adjacent column, such as separate `IPv4` and `IPv6` tabs.

### 8.5 Matching rules

- Matching is **longest-prefix first**, so a customer's `/29` inside a pool
  `/22` resolves to the customer.
- IPs covered by a named entry use that customer.
- IPs covered only by a blank grid entry show **Blank in IP sheet**.
- IPs not covered at all show **Not in IP sheet**.
- Lookup is linear over the sorted entries. Very large sheets (tens of
  thousands of rows) are still workable but slow the build.

## 9. Severity and overrides

Severity normally comes from Shadowserver's `severity` column:

```
critical > high > medium > low > info
```

If Shadowserver supplies an unknown severity, inventory categories fall back
to `info` and everything else to `medium`.

`[severity_overrides]` in the config can **raise** a report type's rating; it
never lowers one. Keys are base report types, so IPv6 and numbered variants
fold onto the same key.

```toml
[severity_overrides]
scan_mikrotik_service = "medium"   # exposed btest/Winbox
scan_http = "low"
```

Overrides are applied when the dashboard is built, not when rows are
ingested. After editing them, run `build` (or `run`). Raised rows show
"Shadowserver rates this ...; raised by local policy" in their detail panel.

## 10. Digest email

Enable the digest with:

```toml
[digest]
enabled = true
smtp_host = "smtp.example.com"
smtp_port = 587
starttls = true
smtp_user = "shadowserver@example.com"
smtp_password = "CHANGE-ME"
from = "shadowserver-dashboard@example.com"
to = ["noc@example.com"]
dashboard_url = "https://shadowserver.example.com/"
```

The digest is sent after a `run` that loaded new rows. It contains:

- the number of new events and how many are actionable (non-info);
- counts for critical, high, medium and low;
- the 15 worst actionable items by severity, then IP;
- the dashboard URL if configured.

`to` must be a TOML array. If the relay rejects the message, the error is
printed to stderr and the dashboard build continues.

## 11. Data, backup and retention

### 11.1 What is stored

Under `data_dir` (default `data/shadowserver` in the example config):

```
data/shadowserver/
├── shadowserver.db        SQLite database: files + findings
├── raw/<date>/*.csv       raw report files, kept for re-ingest
└── inbox/                 folder source
    └── processed/         files already loaded
```

The raw archive is the durable source of truth. The database can be rebuilt
from it.

### 11.2 Retention

- `history_days` limits only what the dashboard *shows*; it does not delete
  rows or raw files.
- The database and raw archive grow indefinitely unless pruned.
- To prune, back up first, then delete old raw date directories and matching
  rows:

```sh
sqlite3 data/shadowserver/shadowserver.db \
  "DELETE FROM findings WHERE report_date < date('now','-365 days');
   DELETE FROM files    WHERE report_date < date('now','-365 days');
   VACUUM;"
```

Remove the corresponding `raw/<date>/` directories as well. This is
destructive; keep a backup until you are satisfied with the result.

### 11.3 Backup

Stop or pause the scheduled run for a consistent copy, then copy the whole
`data_dir`:

```sh
cp -a data/shadowserver "data/shadowserver.backup-$(date +%F)"
```

Alternatively, use SQLite's online backup while the service is running:

```sh
sqlite3 data/shadowserver/shadowserver.db ".backup 'shadowserver.backup.db'"
```

Back up `config/shadowserver.toml` separately and securely; it is not in git.

### 11.4 Full reset

To rebuild the database from the raw archive:

```sh
mv data/shadowserver data/shadowserver.old
mkdir -p data/shadowserver/inbox
find data/shadowserver.old/raw -name '*.csv' -print0 |
  xargs -0 .venv/bin/python -m ssdash -c config/shadowserver.toml ingest
.venv/bin/python -m ssdash -c config/shadowserver.toml build
```

Delete `data/shadowserver.old` once the rebuilt dashboard looks correct.

## 12. BadBox containment

### 12.1 How it works

BadBox and Vo1d are malware families that turn consumer CPEs into bots. This
tooling does not try to block a fixed set of ports. It works from two lists:

The destination addresses are Shadowserver's sinkholes, not the botnets'
real C2 infrastructure — the real C2 is unreachable by construction. The
list is therefore a **detection tripwire**: a device talking to a sinkholed
address is infected. The router-side quarantine is the mitigation.

| List | Populated by | Lifespan |
|---|---|---|
| `Dynamic_BadBox_C2` | the generator, from Shadowserver `dst_ip` values | replaced wholesale each run |
| `BadBox_Quarantine` | the router, when a CPE contacts a listed C2 | each entry expires after 12h |

Because the C2 list contains destination addresses rather than ports, it
survives port rotation. Because quarantine follows the device, it survives
rotation of ports, domains and C2 addresses.

### 12.2 Prerequisites

- ssdash is ingesting reports into `data/shadowserver/shadowserver.db`.
- The database contains sinkhole events (BadBox/Vo1d by default, or any
  family with `--report-types sinkhole`). Check:

  ```sh
  sqlite3 data/shadowserver/shadowserver.db \
    "SELECT DISTINCT issue, report_type FROM findings
     WHERE report_type LIKE '%sinkhole%' ORDER BY 1;"
  ```

- A web server can publish a directory over HTTPS.
- The router trusts that server's certificate chain.
- RouterOS 7.x, and an interface list named `LAN` (or a plan to adapt the
  scripts).

### 12.3 Generate the list by hand

```sh
.venv/bin/python deploy/badbox/generate_c2_list.py \
  --db data/shadowserver/shadowserver.db \
  --out /srv/lists/YOUR-LIST-TOKEN/badbox_c2.rsc
```

Options:

| Option | Default | Meaning |
|---|---|---|
| `--db` | `data/shadowserver/shadowserver.db` | ssdash SQLite database |
| `--out` | **required** | Destination `.rsc` file |
| `--days` | `7` | Lookback window for sinkhole events |
| `--issues` | `badbox,vo1d` | Comma-separated issue substrings to include |
| `--report-types` | none | Comma-separated report-type substrings; when set, `--issues` is ignored (for example `sinkhole`) |
| `--max-staleness-days` | `2` | Refuse if the newest report is older than this |

By default the generator selects rows whose `issue` contains one of the
`--issues` substrings. Pass `--report-types` to select on `report_type`
instead: `sinkhole` matches both `event_sinkhole` and `event_sinkhole_http`
and covers every family Shadowserver sinks (badbox2, vo1d, `avalanche-*`,
sality, ipidea). `--issues` is ignored when `--report-types` is set.

The generator then extracts `dst_ip` from each selected row's `detail` JSON
and counts hits per address. It writes:

```
# Generated 2026-11-06T08:17:55Z from Shadowserver data through 2026-11-05.
# 1 addresses, 7-day lookback. Do not edit by hand.
/ip firewall address-list remove [find list="Dynamic_BadBox_C2"]
/ip firewall address-list add list="Dynamic_BadBox_C2" address=203.0.113.55 comment="auto: 1 hits"
```

The write is atomic (`.tmp` + rename), so a router fetching mid-write never
sees a partial list.

Exit codes:

| Exit | Meaning |
|---|---|
| `0` | List written |
| `1` | Database file not found |
| `2` | No matching addresses in the window; nothing written |
| `3` | Database missing report dates, or stale beyond the threshold; nothing written |

Exit `3` is the one to alert on: it means ingestion has stalled. Exit `2`
is normal when there are no current BadBox hits.

### 12.4 Publish the list over HTTPS

The router fetches the file without credentials, so the path must be
reachable unauthenticated. A minimal nginx location:

```nginx
server {
    listen 443 ssl;
    server_name lists.example.net;
    ssl_certificate     /etc/letsencrypt/live/lists.example.net/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/lists.example.net/privkey.pem;

    location /YOUR-LIST-TOKEN/ {
        alias /srv/lists/YOUR-LIST-TOKEN/;
        autoindex off;
        default_type text/plain;
        add_header Cache-Control "no-store";
    }
}
```

The tokenised path is not authentication. Anyone who learns the URL can read
the list; it only keeps the path out of casual scanning. Rotate it by
renaming the directory and updating `LISTURL` in `refresh.rsc` on every
router.

Verify from another host:

```sh
curl -sS https://lists.example.net/YOUR-LIST-TOKEN/badbox_c2.rsc | head -3
```

### 12.5 Schedule the generator

Run it after the hourly ssdash ingest, for example at minute 25 when ssdash
runs at minute 15:

```cron
25 * * * * cd /opt/ssdash && .venv/bin/python deploy/badbox/generate_c2_list.py --db data/shadowserver/shadowserver.db --out /srv/lists/YOUR-LIST-TOKEN/badbox_c2.rsc >> /var/log/badbox-list.log 2>&1
```

Monitor exit `3`; it means the list is no longer advancing because the
database is stale. A cron mail or a monitoring check on the exit status is
sufficient.

### 12.6 Install the router rules

Before importing, edit `deploy/badbox/refresh.rsc` and replace:

```
https://lists.example.net/YOUR-LIST-TOKEN/badbox_c2.rsc
```

with your real URL. Then, on each router:

```rsc
/import file-name=access-router.rsc
/import file-name=refresh.rsc
```

If the router does not already have a `LAN` interface list:

```rsc
/interface list add name=LAN
/interface list member add list=LAN interface=bridge
```

Replace `bridge` with the actual LAN bridge or interface.

Order matters on a fresh install: `access-router.rsc` creates the rules that
consume `Dynamic_BadBox_C2`, then `refresh.rsc` schedules the fetch. Reversed,
the rules briefly point at an empty list — safe, but misleading.

What the rules do:

1. **Detect** — a TCP connection from a LAN host to a `Dynamic_BadBox_C2`
   address adds the source to `BadBox_Quarantine` for 12h and logs
   `BADBOX-CPE`. The `!BadBox_Quarantine` condition makes the first detection
   log once, not on every packet.
2. **Drop C2 traffic** — drops traffic from LAN hosts to the C2 list. This is
   unlogged on purpose; rule 1 already names the CPE.
3. **Drop quarantined CPEs** — cuts all connectivity for a quarantined device.

Rules are installed in `/ip firewall raw`, chain `prerouting`, scoped to
`in-interface-list=LAN`. If your access router uses a different interface
layout, change `in-interface-list=LAN` in all three rules.

### 12.7 Verify on the router

```rsc
/system script run badbox-c2-refresh
/file print
/ip firewall address-list print where list="Dynamic_BadBox_C2"
/ip firewall raw print where comment~"BadBox"
/log print where message~"BadBox"
```

The fetched file is left in place between runs; its header records the data
date:

```
# Generated 2026-11-06T08:17:55Z from Shadowserver data through 2026-11-05.
```

Inspect the quarantine list after a detection:

```rsc
/ip firewall address-list print where list="BadBox_Quarantine"
```

### 12.8 Tuning

| Change | Where |
|---|---|
| Quarantine duration | `address-list-timeout=12h` in rule 1, then remove and re-import the rule |
| Block only the bot, keep the customer online | Delete rule 3; rule 2 still blocks C2, and the CPE remains labelled |
| Different interface scope | Replace `in-interface-list=LAN` in all three rules |
| Different malware families | `--issues` (comma-separated substrings) |
| Every sinkholed family | `--report-types sinkhole` (ignores `--issues`) |
| Longer/shorter C2 history | `--days` |
| Staleness tolerance | `--max-staleness-days` |
| List name | Constant `LIST_NAME` in `generate_c2_list.py` and the address-list names in `access-router.rsc`; change all together |

### 12.9 Updating rules on a router

The `.rsc` files are idempotent by comment/name: re-importing does **not**
update an object that already exists. To change a rule:

```rsc
/ip firewall raw remove [find where comment="BadBox: detect C2 contact"]
```

Then re-import `access-router.rsc`. For the refresh script:

```rsc
/system script remove [find where name="badbox-c2-refresh"]
```

Then re-import `refresh.rsc`; the existing scheduler still points at the
script name.

### 12.10 Failure behaviour

- If the generator exits `2` or `3`, it writes nothing and the router keeps
  its current list.
- If a router fetch fails, it logs a warning and keeps the current list.
- If an import fails, it logs an error and keeps the current list.
- If the generator stops running entirely, the router keeps re-importing the
  last published file. Monitor the generator's schedule and exit status.

## 13. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Config not found: ...` | No working config | `cp config/shadowserver.example.toml config/shadowserver.toml` |
| `ModuleNotFoundError: No module named 'tomllib'` | Python < 3.11 | Use Python 3.11+ |
| `API test failed: ...` | Wrong key/secret, network block, or API outage | Check credentials and egress; retry |
| `apitest` lists 0 reports | Key not linked to a report set, or `[api] reports` is wrong | Check the report set with Shadowserver |
| IMAP login or folder errors | Wrong host/port/SSL/user/password/folder | Correct `[imap]`; try a mail client with the same settings |
| A Shadowserver mail stays unseen | No attachment and no download link | Inspect the message; load its CSV manually with `ingest` |
| Dashboard is empty | No rows ingested, wrong output path, `history_days` too short, or filters hide rows | Check the ingestion log and filters |
| Expected ≠ rows in the ingestion log | Email count disagrees with the CSV, or a truncated attachment | Inspect the file and re-ingest it |
| Every IP says **Not in IP sheet** | Header names not recognised, or ranges malformed | Check stderr for `customer sheet:` problems; use a recognised header |
| BadBox generator exits `2` | No matching C2 addresses in the window | Normal if there are no current hits; check `--issues` and `--days` |
| BadBox generator exits `3` | Database stale or empty | Check that the hourly ssdash run is succeeding |
| Router fetch fails | Wrong URL, DNS, firewall, or untrusted certificate | Check `/log`; import the CA chain; do not disable certificate checks |
| Rules do not match | `LAN` list missing/empty, or the wrong interface is in it | `/interface list member print where list=LAN` |
| Re-import did not change a rule | The rule already exists and is keyed by comment | Remove the old rule, then re-import |

## 14. Security hardening

- **Config file** — `chmod 600 config/shadowserver.toml`; it contains the
  Shadowserver API secret, mailbox password, and SMTP credentials.
- **Data directory** — restrict to the service account
  (`chmod 700 data`). Raw CSVs and the database contain customer IPs,
  hostnames, and assignment data.
- **Dashboard** — it is a static file, so the web server must enforce
  authentication. Put it behind TLS and an authenticated reverse proxy; do
  not expose it publicly.
- **BadBox list** — the tokenised path is deliberately unauthenticated so
  routers can fetch it. Use HTTPS; the token is not a secret. Rotate it if it
  is abused.
- **Least privilege** — run ssdash as an unprivileged service user. It needs
  read/write only on `data_dir` and the output directory.
- **Backups** — treat them as sensitive; they contain the same customer data
  as the live database.
- **Router credentials** — the BadBox scripts use `/tool fetch` and
  `/import`; they do not store router credentials.

## 15. Command reference

All ssdash commands accept `-c/--config PATH` before the subcommand. The
default is `config.toml`.

| Command | Purpose |
|---|---|
| `python -m ssdash -c PATH run` | Fetch from all configured sources, ingest, digest, build |
| `python -m ssdash -c PATH build` | Rebuild the dashboard from the existing database |
| `python -m ssdash -c PATH apitest [--days N]` | Read-only API check; default 7 days |
| `python -m ssdash -c PATH ingest PATH...` | Load `.csv` / `.csv.zip` files manually |

BadBox generator:

```sh
python deploy/badbox/generate_c2_list.py \
  --db data/shadowserver/shadowserver.db \
  --out /srv/lists/YOUR-LIST-TOKEN/badbox_c2.rsc \
  [--days 7] [--issues badbox,vo1d] [--max-staleness-days 2]
```

Router commands:

```rsc
/import file-name=access-router.rsc
/import file-name=refresh.rsc
/system script run badbox-c2-refresh
/ip firewall address-list print where list="Dynamic_BadBox_C2"
/ip firewall address-list print where list="BadBox_Quarantine"
```

## 16. File layout

```
.
├── config/
│   └── shadowserver.example.toml   configuration template
├── deploy/
│   └── badbox/
│       ├── README.md
│       ├── access-router.rsc       detection / drop / quarantine rules
│       ├── generate_c2_list.py     SQLite -> RouterOS list generator
│       └── refresh.rsc             hourly fetch + import script
├── docs/
│   └── manual.md                   this manual
├── ssdash/
│   ├── __main__.py                 CLI entry point
│   ├── catalog.py                  report titles, categories, guidance
│   ├── customers.py                IP -> customer lookup
│   ├── render.py                   dashboard builder
│   ├── sources.py                  API, IMAP and folder collectors
│   ├── store.py                    CSV normaliser + SQLite store
│   └── template.html               self-contained dashboard page
├── LICENSE
├── README.md
└── requirements.txt
```

---

Licensed under the MIT licence. For concise component summaries, see
[`ssdash/README.md`](../ssdash/README.md) and
[`deploy/badbox/README.md`](../deploy/badbox/README.md).
