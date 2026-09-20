#!/usr/bin/env bash
#
# Report whether updates are waiting, one "Name: Status" line per checker.
#
# The status wording is a contract with lua/dashboard.lua, which keys off it:
#   "<Name>: Updates available"      -> red dot, counted as pending
#   "<Name>: No updates available"   -> green dot
#   "<Name>: Unknown"                -> amber dot; the check could not run
#
# A checker that cannot reach the network must report Unknown rather than
# guessing, otherwise a flaky connection shows up as a phantom update.

set -u

readonly PROGNAME="${0##*/}"

RELEASE=""
OUTPUT=""
CHECK_SBOPKG=0
CHECK_KERNEL=0
CHECK_NVIDIA=0
CHECK_CHROME=0
CHECK_SKYPE=0

###############################
# Helpers
###############################

_die() {
    printf '%s: %s\n' "$PROGNAME" "$1" >&2
    exit 1
}

_need_value() {
    # $1 = flag, $2 = the value that followed it (may be unset)
    if [[ -z "${2:-}" || "${2:-}" == -* ]]; then
        _die "$1 requires an argument."
    fi
}

_report() {
    printf '%s: %s\n' "$1" "$2"
}

# One EXIT trap for both the lock and the temp file; setting two would mean
# the second silently replacing the first.
_cleanup() {
    [[ -n "${TMPFILE:-}" ]] && rm -f "$TMPFILE"
    [[ -n "${LOCKDIR:-}" ]] && rm -rf "$LOCKDIR"
    return 0
}

# The panel re-runs this on a timer, so a slow network check must not get a
# second copy stacked on top of it.  mkdir is atomic on every filesystem worth
# caring about; the pid inside lets a crashed run be cleaned up rather than
# wedging the lock forever.
_acquire_lock() {
    local dir="${TMPDIR:-/tmp}/slackware_updates-$(id -u).lock" owner

    if mkdir "$dir" 2>/dev/null; then
        LOCKDIR="$dir"; echo $$ >"$dir/pid"; return 0
    fi

    owner="$(cat "$dir/pid" 2>/dev/null)"
    if [[ -n "$owner" ]] && kill -0 "$owner" 2>/dev/null; then
        return 1                       # a live run holds it
    fi

    rm -rf "$dir" 2>/dev/null
    if mkdir "$dir" 2>/dev/null; then
        LOCKDIR="$dir"; echo $$ >"$dir/pid"; return 0
    fi
    return 1
}

_printhelp() {
    cat <<EOF
Report pending updates for Slackware and a few out-of-tree packages.

Usage: $PROGNAME -r <release> [options]

  -r, --release <14.2|current>  Which SlackBuilds tree to compare against.
                                Required by --sbopkg.
  -o, --output <file>           Write to <file> atomically instead of stdout,
                                so a reader never sees a half-written file.

Optional checks (all off by default):
      --sbopkg                  SlackBuilds tree is behind
  -k, --kernel                  A newer kernel exists on kernel.org
      --nvidia                  NVIDIA driver is behind
      --google-chrome           Google Chrome is behind
      --skype                   Skype is behind

  -h, --help                    This text.

slackpkg is always checked.  check-updates itself works as a normal user;
only clearing a stale /var/lock/slackpkg.* needs root, and that step is
skipped when not running as root.
EOF
}

# Print the first line of a URL's body, or nothing on failure.
_fetch_first_line() {
    curl --silent --show-error --fail --location --max-time 20 "$1" 2>/dev/null \
        | head -n1
}

###############################
# Checkers
###############################

_check_slackpkg() {
    local out

    # check-updates only reads, so it works as a normal user.  Clearing a
    # stale lock does need root, so skip it rather than failing noisily.
    if [[ $EUID -eq 0 ]]; then
        rm -f /var/lock/slackpkg.* 2>/dev/null
    fi

    if ! command -v /usr/sbin/slackpkg >/dev/null 2>&1; then
        _report Slackpkg "Unknown"
        return
    fi

    out="$(/usr/sbin/slackpkg check-updates 2>/dev/null)" || true

    if [[ -z "$out" ]]; then
        _report Slackpkg "Unknown"
    elif grep -q "AVAILABLE UPDATES" <<<"$out"; then
        _report Slackpkg "Updates available"
    else
        _report Slackpkg "No updates available"
    fi

    if [[ $EUID -eq 0 ]]; then
        rm -f /var/lock/slackpkg.* 2>/dev/null
    fi
}

_check_sbopkg() {
    local web local_ver changelog

    case "$RELEASE" in
        current)
            web="$(_fetch_first_line \
                "https://raw.githubusercontent.com/Ponce/slackbuilds/master/ChangeLog.txt")"
            changelog=/var/lib/sbopkg/SBo-git/ChangeLog.txt
            ;;
        14.2)
            web="$(_fetch_first_line "https://slackbuilds.org/ChangeLog.txt")"
            changelog=/var/lib/sbopkg/SBo/ChangeLog.txt
            ;;
        *)
            _die "--sbopkg needs -r current or -r 14.2 (got '${RELEASE:-none}')."
            ;;
    esac

    local_ver="$(head -n1 "$changelog" 2>/dev/null)"

    if [[ -z "$web" || -z "$local_ver" ]]; then
        _report Sbopkg "Unknown"
    elif [[ "$web" == "$local_ver" ]]; then
        _report Sbopkg "No updates available"
    else
        _report Sbopkg "Updates available"
    fi
}

_check_kernel() {
    local running series latest

    running="$(uname -r)"
    series="${running%%.*}"

    if ! command -v w3m >/dev/null 2>&1; then
        _report Linux "Unknown"
        return
    fi

    # The index lists ChangeLog-<version> files; the highest is the newest.
    latest="$(w3m -dump "https://cdn.kernel.org/pub/linux/kernel/v${series}.x/" 2>/dev/null \
        | grep -o "ChangeLog-${series}\.[0-9.]*" \
        | sed 's/ChangeLog-//' \
        | sort -V \
        | tail -n1)"

    if [[ -z "$latest" ]]; then
        _report Linux "Unknown"
    elif [[ "$running" == "$latest"* ]]; then
        _report Linux "No updates available"
    else
        _report Linux "Updates available"
    fi
}

_check_nvidia() {
    local installed web

    if ! command -v nvidia-smi >/dev/null 2>&1; then
        _report Nvidia "Unknown"
        return
    fi

    installed="$(nvidia-smi 2>/dev/null | grep -o 'Driver Version: [0-9.]*' | awk '{print $3}')"

    # NOTE: this reads NVIDIA's *Vulkan beta* page, which is normally ahead of
    # the stable driver, so a match is unlikely even when fully up to date.
    # Kept as-is to preserve the original behaviour; point it at whichever
    # channel you actually track.
    web="$(curl --silent --fail --max-time 20 "https://developer.nvidia.com/vulkan-driver" 2>/dev/null \
        | grep -o 'Linux driver version [0-9.]*' \
        | head -n1 \
        | awk '{print $4}')"

    if [[ -z "$installed" || -z "$web" ]]; then
        _report Nvidia "Unknown"
    elif [[ "$installed" == "$web" ]]; then
        _report Nvidia "No updates available"
    else
        _report Nvidia "Updates available"
    fi
}

# Both Chrome and Skype ship RPMs whose version is readable from the first few
# hundred bytes, which avoids downloading the whole package just to compare.
_rpm_lead_version() {
    wget --quiet --timeout=20 --tries=2 -O- "$1" 2>/dev/null \
        | head -c 96 \
        | strings \
        | grep -oE "$2"'-[0-9][0-9A-Za-z.]*' \
        | head -n1 \
        | sed "s/^$2-//"
}

_check_installed_version() {
    # $1 = display name, $2 = /var/log/packages prefix, $3 = upstream version
    local name="$1" prefix="$2" version="$3"

    if [[ -z "$version" ]]; then
        _report "$name" "Unknown"
    elif compgen -G "${prefix}${version}-*" >/dev/null; then
        _report "$name" "No updates available"
    else
        _report "$name" "Updates available"
    fi
}

_check_google_chrome() {
    local version
    version="$(_rpm_lead_version \
        "https://dl.google.com/linux/direct/google-chrome-stable_current_x86_64.rpm" \
        "google-chrome-stable")"
    version="${version%%-*}"
    _check_installed_version "Google-Chrome" "/var/log/packages/google-chrome-" "$version"
}

_check_skype() {
    local version
    version="$(_rpm_lead_version "https://repo.skype.com/latest/skypeforlinux-64.rpm" \
        "skypeforlinux")"
    version="${version%%-*}"
    _check_installed_version "Skype" "/var/log/packages/skypeforlinux-" "$version"
}

###############################
# Arguments
###############################

while (( $# )); do
    case "$1" in
        -h|--help)       _printhelp; exit 0 ;;
        -r|--release)    _need_value "$1" "${2:-}"; RELEASE="$2"; shift 2 ;;
        -o|--output)     _need_value "$1" "${2:-}"; OUTPUT="$2";  shift 2 ;;
        -k|--kernel)     CHECK_KERNEL=1; shift ;;
        --nvidia)        CHECK_NVIDIA=1; shift ;;
        --sbopkg)        CHECK_SBOPKG=1; shift ;;
        --google-chrome) CHECK_CHROME=1; shift ;;
        --skype)         CHECK_SKYPE=1;  shift ;;
        --)              shift; break ;;
        # Without these two arms an unrecognised word matches nothing, never
        # shifts, and the loop spins forever.
        -*)              _die "unknown option '$1' (try --help)." ;;
        *)               _die "unexpected argument '$1' (try --help)." ;;
    esac
done

if (( CHECK_SBOPKG )) && [[ -z "$RELEASE" ]]; then
    _die "--sbopkg requires -r current or -r 14.2."
fi

###############################
# Main
###############################

run_all() {
    _check_slackpkg
    (( CHECK_SBOPKG )) && _check_sbopkg
    (( CHECK_KERNEL )) && _check_kernel
    (( CHECK_NVIDIA )) && _check_nvidia
    (( CHECK_CHROME )) && _check_google_chrome
    (( CHECK_SKYPE  )) && _check_skype
    return 0
}

trap _cleanup EXIT INT TERM

if [[ -n "$OUTPUT" ]]; then
    # Only the automated path locks; a manual run to stdout should always work
    # even while the panel's own refresh is in flight.
    if ! _acquire_lock; then
        exit 0                         # a run is already under way: not an error
    fi

    # Write somewhere else and rename, so the panel never reads a file that is
    # half-written or empty because the checks are still running.
    TMPFILE="$(mktemp "${OUTPUT}.XXXXXX")" || _die "cannot create a temporary file."
    run_all >"$TMPFILE"
    mv -f "$TMPFILE" "$OUTPUT"
    TMPFILE=""
else
    run_all
fi
