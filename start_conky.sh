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
#
# Comparing the *resolved* config path matters just as much.  A substring test
# against "$conf" only catches instances spelled with the same absolute path,
# so one started the way the header above suggests --
#
#     conky -c configs/dashboard.conf &
#
# -- survives every restart and quietly draws a second panel over the first.
# A relative path is resolved against that process's cwd, not ours.
conf_real="$(readlink -f -- "$conf" 2>/dev/null || printf '%s' "$conf")"

for pid in $(pgrep -x conky 2>/dev/null || true); do
    mapfile -d '' -t args < "/proc/$pid/cmdline" 2>/dev/null || continue

    cfg=""
    for ((i = 0; i < ${#args[@]}; i++)); do
        case "${args[i]}" in
            -c|--config) cfg="${args[i+1]-}" ;;
            --config=*)  cfg="${args[i]#--config=}" ;;
        esac
    done
    [ -n "$cfg" ] || continue

    case "$cfg" in
        /*) abs="$cfg" ;;
        *)  cwd="$(readlink -- "/proc/$pid/cwd" 2>/dev/null)" || continue
            abs="$cwd/$cfg" ;;
    esac
    abs="$(readlink -f -- "$abs" 2>/dev/null || printf '%s' "$abs")"

    [ "$abs" = "$conf_real" ] && kill "$pid" 2>/dev/null || true
done

conky -c "$conf" ${passthrough[@]+"${passthrough[@]}"} &
