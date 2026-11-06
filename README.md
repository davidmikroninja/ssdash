# ssdash

A small, self-hosted toolkit for acting on Shadowserver reports:

- **`ssdash/`** — ingests Shadowserver reports for your announced address
  space (Reports API, IMAP, or a local folder), stores them in SQLite, and
  builds a single self-contained HTML dashboard for management and NOC use.
- **`deploy/badbox/`** — turns BadBox/Vo1d sinkhole events from that store
  into a RouterOS 7 address list, plus firewall rules that detect and
  quarantine infected CPEs without keying on destination ports.

Everything is environment-neutral: point it at your own report set, mailbox,
output path, and list URL. No customer data or deployment details are
included.

## Requirements

- Python 3.11 or later. The dashboard and BadBox generator use only the
  standard library; `openpyxl` is optional, for `.xlsx` customer sheets.
- RouterOS 7.x for the BadBox firewall scripts.

## Quick start

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp config/shadowserver.example.toml config/shadowserver.toml
$EDITOR config/shadowserver.toml          # API key / IMAP / output path
.venv/bin/python -m ssdash -c config/shadowserver.toml apitest
.venv/bin/python -m ssdash -c config/shadowserver.toml run
```

The default output is `public/shadowserver/index.html`. Run the commands from
the repository root so the `ssdash` package is importable. See
[`ssdash/README.md`](ssdash/README.md) for sources, scheduling, customer
mapping, and severity overrides.

## BadBox containment

`deploy/badbox/generate_c2_list.py` reads the same SQLite database and writes
a RouterOS import that replaces `Dynamic_BadBox_C2` with the current BadBox
/Vo1d C2 addresses. `access-router.rsc` installs the detection and drop rules;
`refresh.rsc` fetches and imports the list hourly. See
[`deploy/badbox/README.md`](deploy/badbox/README.md) for the full setup.

## Security notes

- `config/shadowserver.toml` holds API and mailbox credentials and is
  git-ignored. Keep it that way.
- The generated dashboard contains customer IPs and names. Serve it behind
  authentication and keep it internal.
- The BadBox list path is intentionally unauthenticated so routers can fetch
  it without credentials. Its token is not a secret — it only keeps the path
  out of casual scanning.

## Layout

```
config/shadowserver.example.toml   configuration template
ssdash/                            report ingest, SQLite store, dashboard
deploy/badbox/                     RouterOS C2-list generator and firewall rules
```

## Licence

MIT. See [LICENSE](LICENSE).
