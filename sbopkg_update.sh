#!/bin/bash
#
# Opened in a terminal when the dashboard's Sbopkg row is clicked.
#
# sbopkg needs root, but it is interactive and wants a real terminal, so this
# does not try to elevate on your behalf -- it hands you a shell with the two
# commands spelled out and already in the history.

printf '\n  \033[1mSbopkg needs root.\033[0m\n\n'
printf '    1.  \033[38;5;204msu\033[0m\n'
printf '    2.  \033[38;5;204m/usr/sbin/sbopkg -r\033[0m\n\n'
printf '  Both are in the shell history -- press Up.\n\n'

# Fixed name per user, so repeated runs overwrite rather than accumulate.
hist="${TMPDIR:-/tmp}/.sbopkg-dashboard-history.$(id -u)"
printf '%s\n' '/usr/sbin/sbopkg -r' 'su' > "$hist" 2>/dev/null || hist=""

if [ -n "$hist" ]; then
    HISTFILE="$hist" exec bash -i
fi
exec bash -i
