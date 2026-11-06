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

## Documentation

- **[Operator manual](docs/manual.md)** — installation, full configuration
  reference, dashboard guide, BadBox deployment, troubleshooting.
- [ssdash README](ssdash/README.md) — concise ingest/dashboard overview.
- [BadBox README](deploy/badbox/README.md) — concise RouterOS overview.

## Requirements

- Python 3.11 or later. The dashboard and BadBox generator use only the
  standard library; `openpyxl` is optional, for `.xlsx` customer sheets.
- RouterOS 7.x for the BadBox firewall scripts.

## Getting Shadowserver access

Shadowserver provides reports free to network owners and national CSIRTs for
the networks they control. ssdash does not create or bypass that access; you
need a subscription first.

1. Read the [network reporting overview](https://www.shadowserver.org/what-we-do/network-reporting/)
   and submit the [Subscribe to Reports](https://www.shadowserver.org/what-we-do/network-reporting/get-reports/)
   form with the ASNs or CIDRs you control, report recipients, and whois
   references. An ASN is accepted only if you control it completely; if you
   hold part of an ISP's ASN, list the CIDRs or domains instead.
2. Request API access in the form's References section, or later through the
   [contact form](https://www.shadowserver.org/contact/). Email delivery is
   the default; the API is recommended for automation.
3. Shadowserver vets the request and issues the API key and secret. Put them
   in `[api] key` and `[api] secret` in `config/shadowserver.toml`, then run
   `apitest`.
4. If you receive reports by email instead, configure `[imap]` in the same
   file.

See [Shadowserver's API documentation](https://www.shadowserver.org/what-we-do/network-reporting/api-documentation/)
and the [API utils wiki](https://github.com/The-Shadowserver-Foundation/api_utils/wiki)
for API details, or the [manual's access section](docs/manual.md#getting-shadowserver-access)
for how this repository uses the credentials.

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
a RouterOS import that replaces `Dynamic_BadBox_C2` with current sinkhole
addresses. By default it covers BadBox and Vo1d; `--report-types sinkhole`
broadens it to every family Shadowserver sinks (badbox2, vo1d,
`avalanche-*`, sality, ipidea). The addresses are Shadowserver's sinkholes,
not the botnets' real C2 — the real C2 is unreachable by construction — so
the list is a detection tripwire, and the router-side quarantine is the
mitigation. `access-router.rsc` installs the detection and drop rules;
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
docs/manual.md                     full operator manual
ssdash/                            report ingest, SQLite store, dashboard
deploy/badbox/                     RouterOS C2-list generator and firewall rules
```

## Licence

MIT. See [LICENSE](LICENSE).
