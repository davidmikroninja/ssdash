"""Report-type catalogue: how each Shadowserver feed is labelled, grouped and explained.

Unknown report types are still ingested - `describe()` falls back to rules based
on the type's prefix, so a new feed appearing never breaks a run. Add an entry
here when you want a nicer title or specific remediation text for it.
"""
import re

SEVERITIES = ["critical", "high", "medium", "low", "info"]
SEV_RANK = {s: i for i, s in enumerate(SEVERITIES)}

# Categories, in display order
COMPROMISED = "Compromised host"
BLOCKLISTED = "Blocklisted"
EXPOSED = "Exposed / vulnerable service"
INVENTORY = "Inventory (informational)"

KNOWN = {
    "event_honeypot_brute_force": {
        "title": "Honeypot brute-force attacks",
        "category": COMPROMISED,
        "guidance": "The IP was seen brute-forcing logins (e.g. telnet/SSH) against Shadowserver "
                    "honeypots. Treat as a compromised CPE or IoT device: identify the customer, "
                    "isolate or rate-limit, factory-reset/update firmware and change credentials.",
    },
    "event_sinkhole": {
        "title": "Botnet sinkhole connections",
        "category": COMPROMISED,
        "guidance": "A device behind this IP contacted a sinkholed botnet command server (see the "
                    "'issue' column for the malware family). Notify the customer to clean the "
                    "infected machine; behind NAT, check the CPE's connection table to find it.",
    },
    "event_sinkhole_http": {
        "title": "Botnet sinkhole HTTP connections",
        "category": COMPROMISED,
        "guidance": "An infected device made HTTP requests to a sinkholed malware domain. "
                    "Notify the customer to clean the device.",
    },
    "blocklist": {
        "title": "Third-party blocklists",
        "category": BLOCKLISTED,
        "guidance": "The IP appears on a public blocklist (source shown in the issue). Check why "
                    "it was listed (spam, backscatter, scanning), fix the cause, then request "
                    "delisting from that list.",
    },
    "scan_ntp": {
        "title": "Open NTP (version query)",
        "category": EXPOSED,
        "guidance": "NTP answers mode 6 queries from the internet and can be abused for DDoS "
                    "amplification. Only serve NTP to your own/customer networks: firewall "
                    "UDP 123 from the WAN, or disable the NTP server if it isn't needed.",
    },
    "scan_http": {
        "title": "Accessible HTTP service",
        "category": EXPOSED,
        "guidance": "A web service is reachable from the internet. Confirm it is meant to be "
                    "public; otherwise firewall it. Keep exposed services patched and behind auth.",
    },
    "scan_mikrotik_service": {
        "title": "Exposed MikroTik service",
        "category": EXPOSED,
        "guidance": "A MikroTik management service (bandwidth-test TCP 2000 and/or Winbox 8291) "
                    "is reachable from the internet. Disable the btest server "
                    "(/tool bandwidth-server set enabled=no) and restrict Winbox to management "
                    "networks with firewall rules or /ip service address=.",
    },
    "device_id": {
        "title": "Device identification",
        "category": INVENTORY,
        "guidance": "Shadowserver fingerprinted the device type/vendor on this IP. Informational - "
                    "useful for inventory, and often explains a matching exposed-service finding.",
    },
    "population_isakmp": {
        "title": "IKE / ISAKMP responders",
        "category": INVENTORY,
        "guidance": "Hosts answering IKE on UDP 500 (IPsec VPN endpoints). Informational, not a "
                    "vulnerability. IKEv1 is legacy - move tunnels to IKEv2 where possible and "
                    "disable IPsec on routers that don't need it.",
    },
}


def base_type(report_type: str) -> str:
    """Fold IPv6 / numbered variants onto one key: scan6_x -> scan_x, device_id6 -> device_id,
    event4_x / event6_x -> event_x."""
    t = re.sub(r"^event[46]_", "event_", report_type)
    t = re.sub(r"^(scan|population|special)6_", r"\1_", t)
    t = re.sub(r"^device_id6$", "device_id", t)
    return t


def describe(report_type: str) -> dict:
    b = base_type(report_type)
    if b in KNOWN:
        d = dict(KNOWN[b])
    elif b.startswith("event_") or b.startswith("compromised") or "botnet" in b:
        d = {"title": b.replace("_", " ").capitalize(), "category": COMPROMISED,
             "guidance": "Event report: the IP was observed doing something malicious. "
                         "Investigate the host/customer behind it."}
    elif b.startswith("blocklist") or b.startswith("drone"):
        d = {"title": b.replace("_", " ").capitalize(), "category": BLOCKLISTED,
             "guidance": "IP listed by a third party - find and fix the cause."}
    elif b.startswith("population") or b.startswith("device_id"):
        d = {"title": b.replace("_", " ").capitalize(), "category": INVENTORY,
             "guidance": "Informational inventory report."}
    else:  # scan_*, special_*, anything else
        d = {"title": b.replace("scan_", "Accessible ").replace("_", " ").capitalize(),
             "category": EXPOSED,
             "guidance": "A service is reachable from the internet. Confirm it should be public; "
                         "otherwise firewall or disable it. See Shadowserver's report docs for this type."}
    d["base_type"] = b
    return d


CATEGORY_ORDER = [COMPROMISED, BLOCKLISTED, EXPOSED, INVENTORY]
