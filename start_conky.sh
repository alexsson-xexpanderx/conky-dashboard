#!/usr/bin/env bash
# Optional convenience wrapper: replaces a running panel instead of stacking a
# second one on top.  Nothing here is required -- the config sizes itself and
# the panel refreshes its own data, so this works just as well:
#
#     conky -c configs/dashboard.conf &
#
#   --delay N   wait N seconds before starting.  Used by the autostart entry:
#               configs/dashboard.conf reads _NET_WORKAREA as it is parsed, so
#               it has to run after the desktop has published its panel
#               struts.  conky's own --pause cannot do this, because it sleeps
#               *after* loading the config.
set -eu

here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
conf="$here/configs/dashboard.conf"

delay=0
passthrough=()
while [ $# -gt 0 ]; do
    case "$1" in
        --delay) delay="${2:-0}"; shift 2 ;;
        *)       passthrough+=("$1"); shift ;;
    esac
done

case "$delay" in
    ''|*[!0-9]*) delay=0 ;;
esac
[ "$delay" -gt 0 ] && sleep "$delay"

# Matching on the executable name first matters: a plain `pkill -f "conky -c
# $conf"` also matches any shell whose command line quotes that path --
# including the one running this script.
for pid in $(pgrep -x conky 2>/dev/null || true); do
    if tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -qF -- "$conf"; then
        kill "$pid" 2>/dev/null || true
    fi
done

conky -c "$conf" ${passthrough[@]+"${passthrough[@]}"} &
