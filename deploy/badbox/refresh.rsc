# ══════════════════════════════════════════════════════════════════════════
# BadBox / Vo1d C2 list refresh — RouterOS 7.x
#
# Run once per access router. Fetches the generated address-list file and
# imports it hourly, replacing Dynamic_BadBox_C2 wholesale.
#
# Creates two objects:
#   /system script     badbox-c2-refresh   the work, runnable by hand
#   /system scheduler  badbox-c2-refresh   fires the script hourly
#
# The body lives in a script rather than in the scheduler's on-event because
# /system scheduler has no "run" command -- a scheduler can only be fired by
# its own schedule. With the body in /system script you can test it now:
#
#   /system script run badbox-c2-refresh
#
# LISTURL points at the generated file on whatever web server publishes it.
# The tokenised path is not a credential -- anyone who learns the URL can
# read the list -- it just keeps the path out of casual scanning. Rotate it
# by renaming the directory on the server and updating this value on every
# router.
#
# Requires access-router.rsc to have been imported first, so the rules that
# consume Dynamic_BadBox_C2 exist. Order matters on a fresh install.
# ══════════════════════════════════════════════════════════════════════════

/system script
:if ([:len [find where name="badbox-c2-refresh"]] = 0) do={
    add name="badbox-c2-refresh" \
        policy=ftp,read,write,policy,test \
        source={
            # RouterOS local names must be alphanumeric: LIST_URL and
            # LIST-URL are both rejected at parse time, hence LISTURL.
            :local LISTURL "https://lists.example.net/YOUR-LIST-TOKEN/badbox_c2.rsc"
            :local f "badbox_c2.rsc"
            # Remove any stale copy first, so the existence check below is
            # meaningful. Without this a failed fetch would re-import the
            # previous hour's file and mask the failure.
            :if ([:len [/file find where name=$f]] > 0) do={ /file remove $f }
            :do {
                /tool fetch url=$LISTURL mode=https check-certificate=yes dst-path=$f
            } on-error={
                :log warning "BadBox: C2 list fetch failed; keeping current list"
            }
            :if ([:len [/file find where name=$f]] > 0) do={
                :do {
                    /import file-name=$f
                    :log info "BadBox: C2 list refreshed"
                } on-error={
                    :log error "BadBox: C2 list import failed"
                }
                # Left in place on purpose: its header records the data date,
                # so you can check freshness on the router itself. The next
                # run removes it before fetching.
            }
        }
}

/system scheduler
:if ([:len [find where name="badbox-c2-refresh"]] = 0) do={
    add name="badbox-c2-refresh" interval=1h \
        policy=ftp,read,write,policy,test \
        on-event="/system script run badbox-c2-refresh"
}
