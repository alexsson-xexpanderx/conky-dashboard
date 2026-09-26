# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this directory is

`slackpkg-gui`, a PyQt6 front end for Slackware's package manager, living
inside the conky-dashboard repository because the panel's Slackpkg row launches
it (`update_actions.Slackpkg` in `../lua/dashboard.lua`) and the two share a
palette. See README.md for the GUI's own documentation.

The sections below document how **slackpkg itself** behaves, which the GUI has
to work with. A byte-identical copy of `/usr/sbin/slackpkg` used to sit here
for reference; it is gone. Read the installed one instead — vendoring a copy of
someone else's GPL driver into a public repo buys nothing and silently goes
stale the first time slackpkg is upgraded. Line numbers quoted below are from
slackpkg 16.0.0.

## slackpkg-gui

Python 3 + PyQt6, launched with `./slackpkg-gui`. `slackpkg_gui/backend.py`
parses metadata, `runner.py` builds and escalates the command, `theme.py` holds
the stylesheet, `app.py` is the window.

- **It wraps slackpkg, it does not reimplement it.** Every action shells out to
  `/usr/sbin/slackpkg`, so `functions.d` overrides (slackpkg+ in particular)
  apply exactly as they do on the command line.
- **The list needs no privileges.** `PACKAGES.TXT` and `/var/log/packages` are
  world readable; only actions escalate, via `pkexec`.
- **slackpkg is interactive and is run that way -- on a pty.** Its prompts are
  shown and the user answers them in the box under the log. `-batch=on` with a
  `-default_answer` was the old approach and it is a trap: it answers questions
  the user never sees, and among those questions are "overwrite your /etc
  files?" and "you are out of disk space, continue?". `ConfirmDialog` is still
  the first gate and still shows the exact argv, but it is no longer the only
  one. **Do not reach `SlackpkgRunner.run` without going through it.**
  Turning batch mode off forces three companions, all in runner.py's docstring:
  a pty (so `read` and `stty size` work), `-spinning=off` and `PAGER=cat`
  (both of which `BATCH=on` used to imply, core-functions.sh:107 and :109).
  `PAGER` and `TERM` travel as `env` arguments because pkexec resets the
  environment.
- **"Update" means differs, not newer.** The comparison is on the package
  identifier, matching what slackpkg itself does; a downgrade looks identical.
- **`differs` is not `upgradable`, because of the blacklist.** `makelist`
  filters its list through `applyblacklist` for every command except `search`
  and `download` (core-functions.sh:865-873), and slackpkg+ additionally
  filters the whole pkglist up front (slackpkgplus.sh:1373). So a blacklisted
  package is inert for install, upgrade, reinstall *and* remove -- slackpkg
  skips it and exits 20 having done nothing. `backend.read_blacklist` exists so
  the GUI does not offer those actions. Note `mkregex_blacklist` greps **both**
  the mirror pkglist and `/var/log/packages/*`, which is why a rule like
  `[0-9]+_SBo` matches: it only ever hits the *installed* identifier, never
  what the mirror offers. Match the available id alone and you will find
  nothing and conclude the blacklist is empty.
- **slackpkg writes for a terminal, so its output needs filtering.** The
  progress counter is `printf "%3s%%\b\b\b\b"` (slackpkgplus.sh:1214, :1455)
  -- literal backspaces meant to rewind a cursor. Appended verbatim to a
  QPlainTextEdit they draw as boxes and nothing overwrites, giving a
  `2%****  4%****` trail. slackpkg+ also defines ANSI colour escapes with no
  tty check (slackpkgplus.sh:40-51). `console.tokenize` turns both into
  document edits; `console.render` is the same semantics over plain strings and
  is what the behaviour is checked against.
- **Nothing in slackpkg checks disk space for us, so `ConfirmDialog` does.**
  slackpkg+ *has* that check -- "No sufficient space to download packages...
  (y/N)" at slackpkgplus.sh:1949, and the install equivalent at :1960 -- but
  the GUI never reaches it. `showlist` is defined twice and the copy carrying
  the check is inside `if [ "$DIALOG" = "on" ]` (:1646); `-dialog=off` selects
  the copy at :1979, which has no check. `CHECKDISKSPACE` is also off by
  default. Two independent reasons, so do not "fix" this by reinstating the
  prompt -- it cannot fire. `backend.space_report` sizes the operation from
  PACKAGES.TXT and `ConfirmDialog` shows it, turning Proceed into the danger
  variant and putting Enter on Cancel when it does not fit. The figures err
  high on purpose: the space an outgoing version gives back is not subtracted,
  because slackpkg unpacks the new package before removing the old one. Note
  slackpkg+'s own install check compares `available` against `compressed`
  rather than `uncompressed` (:1959), which understates it; ours does not.
- **install-new runs before upgrade-all, and the toolbar is ordered to say so.**
  `upgrade-all` only touches packages already installed, so anything the
  release has newly added -- or newly split out of a package you have -- stays
  missing, and the upgraded half may expect it. `backend.pending_new_packages`
  detects this rather than guessing: install-new is ChangeLog-driven, not
  "everything not installed", so it invokes the real
  `/usr/libexec/slackpkg/install-new.awk` over ChangeLog.txt and keeps the
  names a repo offers and the system lacks (core-functions.sh:797-808), plus
  the eight hardcoded extras at :798-801. This is the only subprocess in
  backend.py and it is read-only. When any are pending, `do_upgrade_all` raises
  a warning in `ConfirmDialog` and Cancel becomes the default.
- **`setDefault(True)` alone does not survive `show()`.** `QDialogButtonBox`
  re-asserts its AcceptRole button as the default when the dialog is shown, so
  wiring Enter to Cancel needs `setAutoDefault(False)` on the other button as
  well. This was silently broken -- the destructive-removal dialog *looked*
  right while Enter still proceeded -- which is why `default_test` asserts the
  flag after `show()` rather than after construction. Do not "simplify" that
  loop back into a single setDefault call.
- **`-postinst=on`, so `looknew` asks the user about .new files.** That prompt
  (K/O/R/P, post-functions.sh:126) decides whether live `/etc` files are
  replaced, which is exactly the kind of decision a front end must not make.
  `backend.find_new_config_files` still reports what is left afterwards, but it
  reports only -- **nothing in this program writes to /etc**, and no code path
  should act on a .new file.
- **The pty is sized 400x120 on purpose.** `looknew` compares the number of
  .new files against `$ROWS` and drops into a press-SPACE-to-scroll mode when
  they do not fit (post-functions.sh:189), which a widget that does not emulate
  a screen cannot render. A tall pty means that branch never runs. The old
  `stty: Inappropriate ioctl` and `[: N: unary operator expected` noise came
  from running on a pipe and is gone.
- `./slackpkg-gui --screenshot out.png` renders the window and exits, which
  works under `QT_QPA_PLATFORM=offscreen` — use it to check layout changes
  without a display rather than guessing.

## /usr/sbin/slackpkg is only a dispatcher

The 625-line Bash driver does almost nothing itself. Line ~86 does:

```
. /usr/libexec/slackpkg/core-functions.sh
```

That 42KB library defines nearly everything the driver calls — `system_setup`,
`system_checkup`, `makelist`, `showlist`, `install_pkg`, `upgrade_pkg`,
`remove_pkg`, `getpkg`, `checkchangelog`, `updatefilelists`, `cleanup`,
`answer`. The driver's own job is: guard against a bogus system clock, load
config, parse the command line, dispatch through one large `case "$CMD"`, then
run the post-install hooks. When something surprising happens, the answer is
almost always in core-functions.sh or a `functions.d` override, not the driver.

**The paths are absolute**, so there is no way to run a modified driver against
unmodified functions without also editing its `.` line. Upstream:
https://slackpkg.org/

## functions.d overrides core by redefinition

After sourcing core, the driver sources every executable `/usr/libexec/slackpkg/functions.d/*.sh`.
These are plain shell files, so **a function defined there silently replaces the core one**, and
because the glob is alphabetical, load order decides the winner. On this machine:

```
dialog-functions.sh  post-functions.sh  slackpkgplus.sh  zchangelog.sh  zlookkernel.sh
```

The `z` prefixes are deliberate — they make those files load last so their definitions win. The
resulting picture is not stock slackpkg:

| function | defined in | effective |
|---|---|---|
| `showlist` | core, dialog-functions, slackpkgplus | slackpkgplus |
| `install_pkg` / `upgrade_pkg` / `remove_pkg` / `getpkg` | core, slackpkgplus | slackpkgplus |
| `cleanup` | core, slackpkgplus, zchangelog | zchangelog |
| `lookkernel` | post-functions, zlookkernel | zlookkernel |
| `looknew` / `lookoldpkgfiles` | post-functions | post-functions |

`slackpkgplus.sh` is 106KB — larger than core-functions.sh — and belongs to the third-party
`slackpkg+` package (1.8.3 installed alongside slackpkg 16.0.0). Before concluding that a package
operation behaves the way core-functions.sh says, check whether slackpkg+ has replaced that
function.

## Checking and running

The GUI has no build step and no test suite. The syntax check is:

```bash
python3 -m py_compile slackpkg_gui/*.py
```

and `./slackpkg-gui --screenshot out.png` renders the window and exits under
`QT_QPA_PLATFORM=offscreen`, which is how layout changes get checked without a
display. Driving a click needs a harness: build the window, poke the widget,
then read the state back — see the console and confirm-dialog tests described
above.

Running **slackpkg** is a different matter. Most subcommands need root and **mutate the live system** —
`upgrade-all`, `install`, `remove`, `clean-system`, `install-new`, `new-config`, and the
`*-template` pair all install or delete packages. `update` writes metadata to `/var/lib/slackpkg`.
Even nominally read-only commands (`search`, `file-search`, `info`, `check-updates`,
`show-changelog`) depend on the mirror metadata and may reach the network. Do not invoke these to
"see what happens" on this machine — it is the user's actual Slackware install.

## Things that will trip you up

- **Option syntax is non-standard.** Flags are single-dash with an inline value —
  `-checkgpg=off`, `-batch=on`, `-mirror=URL`, `-default_answer=y`. There is no getopt; it is a
  hand-rolled `while`/`case` loop, and an unrecognised token falls through to `usage`.
- **`$ROOT` re-roots the config**, not just the target: `CONF` becomes `${ROOT}/etc/slackpkg` and
  `WORKDIR` is prefixed too. Used for installing into an alternate root.
- **`SOURCE` is parsed out of `$CONF/mirrors` by an inline sed program**, not sourced. It accepts
  only `file:// cdrom:// local:// http(s):// ftp(s)://`, requires exactly one token per line, and
  appends a trailing solidus. A mirror line with trailing text is silently dropped.
- **Post-install hooks run by default.** After the dispatch, `lookoldpkgfiles`, `lookkernel` and
  `looknew` run unless `POSTINST=off`. The driver force-disables them for a fixed list of commands
  (`check-updates remove search file-search update info blacklist clean-system download
  generate-template remove-template`), and several error branches set `POSTINST=off` before
  bailing. If you add a subcommand, decide explicitly which side of that list it belongs on.
- **`upgrade-all` bootstraps itself in a specific order**: if the list contains `slackpkg` it
  upgrades that alone, tells the user to rerun, and exits **50**. Otherwise it force-upgrades
  `pkgtools aaa_glibc-solibs glibc-solibs aaa_libraries aaa_elflibs mkinitrd readline sed` ahead of
  everything else. That ordering is load-bearing — breaking it can leave a system unable to run
  the tools needed to finish.
- **Exit codes are meaningful**: `20` = nothing matched the pattern, `50` = slackpkg upgraded
  itself and must be rerun, `100` = `check-updates` found updates (so cron notifies).

## Configuration

`/etc/slackpkg/` holds `slackpkg.conf` (sourced directly, `WORKDIR=/var/lib/slackpkg`), `mirrors`,
`blacklist`, `greylist`, `notifymsg.conf`. Note this system also has `.orig` and `~` copies
(`mirrors.orig`, `slackpkg.conf.orig`, `blacklist~`) — local edits have been made, so don't assume
the files match a stock install.
