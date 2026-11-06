# BadBox / Vo1d containment

Firewall tooling for RouterOS 7 access routers, fed from the Shadowserver
ingest in this repository. For the full deployment walkthrough and tuning
reference, see the [operator manual](../../docs/manual.md#12-badbox-containment).

## Why it is not a port list

A hand-maintained set of destination ports does not work: Shadowserver's
sinkhole only records what reaches its own listeners, so **the feed is
structurally blind to whichever port the bot rotates to next**. There is no
data source here that could tell you which port to add tomorrow.

This tooling stops keying on the port:

- **Destination addresses** (`Dynamic_BadBox_C2`) — rebuilt hourly from the
  `dst_ip` field of BadBox/Vo1d sinkhole events, port-agnostic.
- **The CPE itself** (`BadBox_Quarantine`) — any CPE that opens a TCP
  connection to a known C2 is labelled for 12h and dropped. TCP only: the
  C2 is HTTP over TCP, so ICMP and UDP cannot trigger a false positive
  against shared hosting addresses. This survives rotation of ports, domains
  *and* C2 addresses, because it follows the device, not the traffic.

## Layout

```
host publishing lists                        access router
────────────────────                        ─────────────
cron :25 ─► generate_c2_list.py ─► /srv/lists/<token>/badbox_c2.rsc
                                          │
                                     web server (TLS, unauthenticated path)
                                          │
                                          ▼
                                   /tool fetch (hourly, scheduler)
                                          └─► /import ─► Dynamic_BadBox_C2
```

## The two address lists

| List | Populated by | Lifespan |
|---|---|---|
| `Dynamic_BadBox_C2` | the hourly job that runs `generate_c2_list.py`; fetched and imported | replaced wholesale each run |
| `BadBox_Quarantine` | **the router itself**, via `add-src-to-address-list` in rule 1 | each entry expires after 12h |

`BadBox_Quarantine` has no external generator and nothing seeds it. In
RouterOS an address list is not a standalone object — it exists only as the
`list` property of its entries — so there is nothing to create in advance.
It materialises the first time a CPE opens a TCP connection to a listed C2
and disappears again once its last entry times out. Rule 3 referencing it while empty
matches nothing, which is intended; `src-address-list="!BadBox_Quarantine"`
is true when the list is absent, which is what lets the first detection fire.

To inspect it: `/ip firewall address-list print where list="BadBox_Quarantine"`.

## Files

| Path | What |
|---|---|
| `generate_c2_list.py` | Reads ssdash's SQLite, writes the RouterOS import |
| `access-router.rsc` | Detect / drop-C2 / drop-quarantined rules (RouterOS 7) |
| `refresh.rsc` | Hourly fetch + import: a `/system script` plus a scheduler (RouterOS 7) |

The `.rsc` files expect the list to be published at the URL set in
`refresh.rsc`; replace `YOUR-LIST-TOKEN` with a path segment of your choosing.

## One-time setup

### On the host that runs ssdash

```sh
# 1. Directory the generator writes to and the web server serves from.
sudo install -d -o "$USER" -g "$(id -gn)" -m 755 /srv/lists/YOUR-LIST-TOKEN

# 2. Produce the first list before any router asks for it.
.venv/bin/python deploy/badbox/generate_c2_list.py \
  --db data/shadowserver/shadowserver.db \
  --out /srv/lists/YOUR-LIST-TOKEN/badbox_c2.rsc

# 3. Serve /srv/lists over HTTPS, with the tokenised path left unauthenticated.
```

Cron, alongside the hourly `ssdash run`:

```cron
25 * * * * cd /path/to/ssdash && .venv/bin/python deploy/badbox/generate_c2_list.py --db data/shadowserver/shadowserver.db --out /srv/lists/YOUR-LIST-TOKEN/badbox_c2.rsc >> data/badbox-list.log 2>&1
```

### On each access router

```rsc
/import file-name=access-router.rsc
/import file-name=refresh.rsc
```

`access-router.rsc` refuses to install anything if the `LAN` interface list
does not exist — it logs an error, prints how to create it, and stops. It
also warns (without stopping) if the list exists but has no members, since
rules scoped to an empty list match nothing.

**Order matters on a fresh install:** `access-router.rsc` first creates the
rules that consume `Dynamic_BadBox_C2`; `refresh.rsc` then schedules the
fetch. Reversed, the rules briefly point at an empty list — safe (they drop
nothing) but it looks like it is working when it is not.

## Verifying

From anywhere with network access:

```sh
curl -sS https://lists.example.net/YOUR-LIST-TOKEN/badbox_c2.rsc | head -3
```

On the router, trigger the first run by hand — the body is a `/system script`,
so it can be run directly. (`/system scheduler` has no `run` command; a
scheduler only fires on its own schedule.)

```rsc
/system script run badbox-c2-refresh
/file print
/ip firewall address-list print where list="Dynamic_BadBox_C2"
/log print where message~"BadBox"
```

The fetched file is left in place between runs, so its first two lines tell
you how fresh the data is:

```
# Generated 2026-10-19T15:07:46Z from Shadowserver data through 2026-10-18.
# 11 addresses, 7-day lookback. Do not edit by hand.
```

## Failure behaviour

The generator refuses to write in two cases, both leaving the router's
current list in place:

| Exit | Condition |
|---|---|
| `2` | No matching addresses in the lookback window |
| `3` | Database stale — newest report older than `--max-staleness-days` (default 2) |

Exit `3` is the one to alert on: it means the hourly Shadowserver ingest has
died, and the list is no longer being refreshed. Without it the generator
would keep re-publishing yesterday's addresses and nothing would look wrong.

The write is atomic (`.tmp` + rename), so a router fetching mid-write never
sees a partial list. On the router, a failed fetch or import logs a warning
and keeps the existing list.

## Caveats

- **TLS trust.** `/tool fetch` uses `check-certificate=yes`. If a router does
  not trust the web server's chain, import the CA root under `/certificate` —
  do not disable verification.
- **The token is not a secret.** Anyone who learns the URL can read the list.
  It exists to keep the path out of casual scanning. Rotate by renaming the
  directory and updating `LISTURL` in `refresh.rsc`.
- **Quarantine is a full drop.** Rule 3 in `access-router.rsc` cuts the
  device's connectivity entirely. To block only the bot and leave the
  customer online, delete that rule — the device stays labelled in
  `BadBox_Quarantine` either way, so you still get a log line naming it.
- **CPE devices are typically unfixable.** The user agents in the telemetry
  are `MBOX` and `TVBOX` Android builds. BadBox 2.0 is generally preinstalled
  at manufacture and cannot be cleaned by the customer; the realistic outcome
  is quarantine plus telling them to replace the box.
