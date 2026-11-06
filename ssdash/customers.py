"""Map IPs to customers from the public IP assignment sheet.

Reads .csv natively, .xlsx if openpyxl is installed. Columns are found by header name
(case-insensitive), so the sheet can be exported as-is:

  address   one of: cidr, prefix, subnet, network, ip, ip address, address, block, range
            (a single IP, a CIDR, or "a.b.c.d - a.b.c.e"), or a pair of start/end columns
  customer  one of: customer, client, name, company, account, customer name
  extra     any of: account no / customer id, service, site, contact, notes - carried into the dashboard

Grid layout (e.g. the "IPv4" / "IPv6" tabs): sheets without such a header are
read as a grid - every cell holding an IP or CIDR takes its label from the cell to its right.
Blank labels are recorded as "blank in IP sheet" and only used when nothing named matches.

Lookups are longest-prefix-match, so a /29 assigned to a customer wins over the /22 it sits in.
The sheet is re-read on every build, so editing it updates the dashboard's history too.
"""
import csv
import ipaddress
from pathlib import Path

ADDR_COLS = ["cidr", "prefix", "subnet", "network", "ip address", "ip", "address", "block", "range", "ip range", "public ip"]
START_COLS = ["start", "start ip", "from", "first ip"]
END_COLS = ["end", "end ip", "to", "last ip"]
NAME_COLS = ["customer", "customer name", "client", "client name", "company", "name", "account name", "account"]
EXTRA_COLS = {"account": ["account no", "account number", "customer id", "client id", "acc no", "code"],
              "service": ["service", "product", "package"],
              "site": ["site", "location", "pop", "tower"],
              "contact": ["contact", "email", "contact email"],
              "notes": ["notes", "comment", "comments", "description"]}


def _norm(h):
    return " ".join(str(h or "").strip().lower().replace("_", " ").split())


def _pick(headers, names):
    hs = [_norm(h) for h in headers]
    for n in names:
        if n in hs:
            return hs.index(n)
    return None


def _as_net(v):
    v = str(v or "").strip()
    if not v or not any(ch.isdigit() for ch in v) or ("." not in v and ":" not in v):
        return None
    try:
        return ipaddress.ip_network(v, strict=False)
    except ValueError:
        return None


def _rows(path: Path, sheets=None):
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        try:
            import openpyxl
        except ImportError:
            raise SystemExit("Reading .xlsx needs openpyxl (pip install openpyxl) - or export the sheet as CSV.")
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        for ws in wb.worksheets:
            if sheets and ws.title not in sheets:
                continue
            yield ws.title, [list(r) for r in ws.iter_rows(values_only=True)]
    else:
        with open(path, newline="", encoding="utf-8-sig") as f:
            yield path.stem, list(csv.reader(f))


def _networks(value, start=None, end=None):
    if start and end:
        a, b = ipaddress.ip_address(str(start).strip()), ipaddress.ip_address(str(end).strip())
        return list(ipaddress.summarize_address_range(a, b))
    v = str(value or "").strip()
    if not v:
        return []
    if "-" in v and "/" not in v:
        a, b = (p.strip() for p in v.split("-", 1))
        if "." in a and "." not in b:  # 192.0.2.10-20 (RFC 5737 documentation range)
            b = a.rsplit(".", 1)[0] + "." + b
        return list(ipaddress.summarize_address_range(ipaddress.ip_address(a), ipaddress.ip_address(b)))
    return [ipaddress.ip_network(v, strict=False)]


class CustomerMap:
    def __init__(self, path=None, sheets=None):
        self.entries = []  # (network, info) - named
        self.blank = []    # networks listed with no name
        self.problems = []
        if path:
            self.load(Path(path), sheets)

    def _grid(self, sheet, rows):
        for r in rows:
            r = list(r)
            for i, v in enumerate(r):
                net = _as_net(v)
                if not net:
                    continue
                label = r[i + 1] if i + 1 < len(r) else None
                label = "" if label is None or _as_net(label) else str(label).strip()
                if label:
                    self.entries.append((net, {"customer": label, "sheet": sheet}))
                else:
                    self.blank.append(net)

    def load(self, path: Path, sheets=None):
        for sheet, rows in _rows(path, sheets):
            # header = first row that has both an address column and a customer column
            hdr_i = next((i for i, r in enumerate(rows[:20])
                          if (_pick(r, ADDR_COLS) is not None or _pick(r, START_COLS) is not None)
                          and _pick(r, NAME_COLS) is not None), None)
            if hdr_i is None:
                self._grid(sheet, rows)
                continue
            hdr = rows[hdr_i]
            ai, si, ei = _pick(hdr, ADDR_COLS), _pick(hdr, START_COLS), _pick(hdr, END_COLS)
            ni = _pick(hdr, NAME_COLS)
            xi = {k: _pick(hdr, v) for k, v in EXTRA_COLS.items()}
            for n, r in enumerate(rows[hdr_i + 1:], start=hdr_i + 2):
                r = list(r) + [None] * (len(hdr) - len(r))
                name = str(r[ni] or "").strip()
                try:
                    nets = _networks(r[ai] if ai is not None else None,
                                     r[si] if si is not None and ei is not None else None,
                                     r[ei] if si is not None and ei is not None else None)
                except ValueError as e:
                    self.problems.append(f"{sheet} row {n}: {e}")
                    continue
                if not nets:
                    continue
                info = {"customer": name or "(unassigned)"}
                info.update({k: str(r[i]).strip() for k, i in xi.items() if i is not None and r[i] not in (None, "")})
                self.entries += [(net, info) for net in nets]
        # most specific first -> first match is the longest prefix
        self.entries.sort(key=lambda e: -e[0].prefixlen)
        # Only workbook inputs can be missing a requested sheet. For a CSV the
        # single implicit sheet name never matches, and reporting the
        # configured names as missing would be pure noise.
        if sheets and path.suffix.lower() in (".xlsx", ".xlsm"):
            missing = set(sheets) - {s for s, _ in _rows(path, sheets)}
            self.problems += [f"sheet not found: {m}" for m in sorted(missing)]

    def lookup(self, ip: str):
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return None
        for net, info in self.entries:
            if addr.version == net.version and addr in net:
                return info
        if any(addr.version == n.version and addr in n for n in self.blank):
            return {"customer": "", "blank": "yes"}
        return None
