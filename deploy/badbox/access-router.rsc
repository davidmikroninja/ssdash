# ══════════════════════════════════════════════════════════════════════════
# BadBox / Vo1d containment — access router
# RouterOS 7.x
#
# Run once per access router:  /import file-name=access-router.rsc
# Idempotent: each rule is only added if a rule with its comment is absent.
# Consequence: editing a rule here does NOT update a router that already has
# it. Remove the old rule first, then re-import -- or change it in place with
#   /ip firewall raw set [find where comment="<comment>"] <property>=<value>
#
# Prerequisites:
#   * an interface list named "LAN"; if you use a bridge instead, replace
#     in-interface-list=LAN with in-interface=<your-lan-bridge> below.
#     Checked below: the script stops without installing anything if the
#     list is missing, rather than adding rules that can never match.
#   * Dynamic_BadBox_C2 populated by the hourly refresh (see refresh.rsc).
#
# Order matters. RouterOS evaluates raw rules top-down:
#   1. detect   -> label the CPE
#   2. drop C2  -> stop this packet too
#   3. drop CPE -> keep it stopped
# ══════════════════════════════════════════════════════════════════════════

# ── Preflight: the LAN interface list must exist ─────────────────────────
# Rules scoped to a list that does not exist still install, and never match.
# From the outside that is indistinguishable from "nothing to block", which
# is exactly the failure this design exists to avoid. Stop instead.
/interface list
:if ([:len [find where name="LAN"]] = 0) do={
    :log error "BadBox: interface list LAN not found - no rules installed"
    :put "ERROR: interface list \"LAN\" does not exist."
    :put "  Create it:  /interface list add name=LAN"
    :put "              /interface list member add list=LAN interface=<your-lan-bridge>"
    :put "  Or replace in-interface-list=LAN with in-interface=<bridge> in this script."
    :error "BadBox: LAN interface list missing"
}

# Exists but has no members is the same silent no-op. Warn rather than stop:
# members may be added later, and the rules go live as soon as they are.
:if ([:len [/interface list member find where list="LAN"]] = 0) do={
    :log warning "BadBox: interface list LAN exists but has no members - rules will not match until it does"
}

/ip firewall raw

# ── 1. Detection ─────────────────────────────────────────────────────────
# Any CPE that opens a TCP connection to a known C2 is quarantined for 12h.
# TCP only: Badbox's C2 is HTTP over TCP, so coverage of the threat is
# unchanged, while ICMP and UDP -- plausible false-positive paths against
# shared hosting addresses on the list -- no longer trigger a full
# quarantine. Still port-agnostic, which is the property that matters.
# The !BadBox_Quarantine condition means a given CPE logs once, not on every
# packet it sends while still being onboarded.
# NOTE: add-src-to-address-list does not terminate the rule list, so this
# packet continues into rule 2 and is dropped there as well.
:if ([:len [find where comment="BadBox: detect C2 contact"]] = 0) do={
    add chain=prerouting in-interface-list=LAN \
        protocol=tcp \
        dst-address-list="Dynamic_BadBox_C2" \
        src-address-list="!BadBox_Quarantine" \
        action=add-src-to-address-list \
        address-list="BadBox_Quarantine" \
        address-list-timeout=12h \
        comment="BadBox: detect C2 contact" \
        log=yes log-prefix="BADBOX-CPE "
}

# ── 2. Drop traffic to the C2 list ───────────────────────────────────────
# Rule 2 drops traffic to known C2 addresses. Unlogged on purpose: a
# retrying bot would flood the log. Rule 1 already names the CPE once.
:if ([:len [find where comment="BadBox: drop C2 destinations"]] = 0) do={
    add chain=prerouting in-interface-list=LAN \
        dst-address-list="Dynamic_BadBox_C2" \
        action=drop \
        comment="BadBox: drop C2 destinations"
}

# ── 3. Drop quarantined CPEs ─────────────────────────────────────────────
# FULL quarantine: the device loses all connectivity, not just C2 access.
# If you would rather only block the bot and leave the customer online,
# delete this rule and rely on rule 2 alone -- the CPE stays labelled in
# BadBox_Quarantine either way, so you still get the log line naming it.
:if ([:len [find where comment="BadBox: drop quarantined CPE"]] = 0) do={
    add chain=prerouting in-interface-list=LAN \
        src-address-list="BadBox_Quarantine" \
        action=drop \
        comment="BadBox: drop quarantined CPE"
}

:log info "BadBox: access-router rules present"
