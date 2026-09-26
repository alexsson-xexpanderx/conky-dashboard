r"""Running slackpkg on behalf of the GUI.

Everything here wraps the real /usr/sbin/slackpkg rather than reimplementing
any of it -- package management is not something to reinvent in a front end.

slackpkg is an interactive script, and this runs it as one: its prompts are
shown and the user answers them. The alternative -- `-batch=on` with a
`-default_answer` -- means the GUI silently answers questions the user never
sees, and some of those questions are "may I overwrite your /etc files?" and
"you are out of disk space, continue?". Answering those on someone's behalf is
not a convenience.

That choice forces three things:

  * **A pty, not a pipe.** `answer()` does a bare `read ANSWER`, and slackpkg
    sizes its output with `stty size`. Over a pipe `stty` fails outright --
    "Inappropriate ioctl for device" -- leaving `$ROWS` empty and producing
    `[: N: unary operator expected` from post-functions.sh:189. A pty makes all
    of that behave as it does in a terminal.

  * **-spinning=off.** `BATCH=on` used to force this (core-functions.sh:107).
    Without it `spinning()` animates |/-\ in place using `tput sc`/`tput rc`,
    and a QPlainTextEdit cannot restore a cursor position, so the frames pile
    up into a line of junk instead of spinning.

  * **PAGER=cat.** `BATCH=on` also forced `MORECMD=cat` (:109). Without it
    `showlist` pipes the package list through `more`, which pages against a
    real tty -- and our pty *is* real, so it would genuinely stop and wait at a
    `--More--` prompt drawn with control codes the console strips. Setting
    PAGER makes MORECMD `cat` again (:116).

PAGER has to travel as an `env` argument rather than in the environment,
because pkexec deliberately resets the environment to a minimal safe set before
running anything. Our own fork could just pass it, but the privileged path
cannot.

TERM travels the same way and is set to xterm rather than left unset. Under
`dumb`, `tput sc` in post-functions.sh:15 fails outright and prints an error
for every menu line; under xterm it emits ESC 7, which console.py strips. An
escape we discard beats a diagnostic we have to read.

-dialog=off stays: the console renders text, not ncurses.

ConfirmDialog still runs first and still shows the exact argv. It is no longer
the *only* refusal point, which is an improvement -- it is now the first of
two, and the second one lists what slackpkg actually resolved.
"""

from __future__ import annotations

import fcntl
import os
import pty
import shutil
import signal
import struct
import termios

from PyQt6.QtCore import QObject, QSocketNotifier, pyqtSignal

SLACKPKG = "/usr/sbin/slackpkg"
ENV = "/usr/bin/env"

# Commands that only read. Everything else changes installed packages or the
# metadata in /var/lib/slackpkg and therefore needs root.
READ_ONLY = {"search", "file-search", "info", "show-changelog", "blacklist", "help"}

# The pty's reported size. Deliberately tall: looknew (post-functions.sh:189)
# compares the number of .new files against $ROWS and switches to a
# press-SPACE-to-scroll mode when they do not fit, which is unreadable in a
# widget that does not emulate a screen. At this height it never does.
PTY_ROWS, PTY_COLS = 400, 120

# From the big case in the driver script.
EXIT_MEANING = {
    0: "Finished.",
    20: "No packages matched.",
    50: "slackpkg upgraded itself -- run the operation again.",
    100: "Updates are available.",
}

# Exit 20 is "nothing matched the pattern", which reads as a failure but is the
# ordinary success case for the commands that take no pattern -- there was
# simply nothing to do.
NOTHING_TO_DO = {
    "upgrade-all": "Nothing to upgrade -- already up to date.",
    "install-new": "No new packages to install.",
    "clean-system": "No packages to remove.",
}


def exit_meaning(code: int, command: str = "") -> str:
    if code == 20 and command in NOTHING_TO_DO:
        return NOTHING_TO_DO[command]
    if code == -1:
        return "Stopped."
    return EXIT_MEANING.get(code, f"Exited with status {code}.")


def privilege_tool() -> str | None:
    """pkexec first: on KDE it raises the polkit agent rather than needing a tty."""
    for tool in ("pkexec", "sudo"):
        path = shutil.which(tool)
        if path:
            return path
    return None


def build_argv(command: str, packages: list[str] | None = None) -> list[str]:
    args = [SLACKPKG]
    if command not in READ_ONLY:
        args += ["-dialog=off", "-spinning=off", "-postinst=on"]
    args.append(command)
    args += packages or []

    if command in READ_ONLY:
        return args
    tool = privilege_tool()
    if not tool:
        return args
    # env carries PAGER and TERM across pkexec, which resets the environment.
    return [tool, ENV, "PAGER=cat", "TERM=xterm", *args]


def describe(command: str, packages: list[str] | None = None) -> str:
    return " ".join(build_argv(command, packages))


class SlackpkgRunner(QObject):
    """One slackpkg invocation at a time, on a pty, with input sent back to it."""

    output = pyqtSignal(str)
    started = pyqtSignal(str)
    finished = pyqtSignal(int, str)
    # True while the child has switched the terminal's echo off, which is how
    # every well-behaved password prompt asks for a secret. Handing a pty to
    # pkexec means it may authenticate through a text prompt rather than the
    # KDE polkit dialog, and a password typed into a plain QLineEdit would sit
    # on screen in clear. Reading the flag off the pty is exact -- no guessing
    # from the prompt's wording.
    secret_input = pyqtSignal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pid: int | None = None
        self._master: int | None = None
        self._notifier: QSocketNotifier | None = None
        self._command = ""
        self._secret = False

    @property
    def busy(self) -> bool:
        return self._pid is not None

    def run(self, command: str, packages: list[str] | None = None) -> bool:
        if self.busy:
            return False

        argv = build_argv(command, packages)
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ,
                    struct.pack("HHHH", PTY_ROWS, PTY_COLS, 0, 0))

        self._command = command
        self.started.emit(" ".join(argv))

        pid = os.fork()
        if pid == 0:
            # Child. Nothing here may raise past the exec: a Python traceback
            # in a forked copy of a Qt application would be a second process
            # trying to own the same window.
            try:
                os.setsid()
                fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
                for target in (0, 1, 2):
                    os.dup2(slave, target)
                if slave > 2:
                    os.close(slave)
                os.close(master)
                os.execvp(argv[0], argv)
            except BaseException:
                os._exit(127)

        os.close(slave)
        self._pid = pid
        self._master = master
        self._notifier = QSocketNotifier(master, QSocketNotifier.Type.Read)
        self._notifier.activated.connect(self._drain)
        return True

    def send(self, text: str) -> bool:
        """Answer a prompt. The pty echoes it back, so it lands in the log too."""
        if self._master is None:
            return False
        try:
            os.write(self._master, (text + "\n").encode("utf-8"))
        except OSError:
            return False
        return True

    def cancel(self) -> None:
        """Stop the run.

        A privileged child is root and a plain kill(2) from our uid is refused,
        so this closes the pty instead: the kernel hangs up the session, which
        the child sees as its terminal disappearing. SIGTERM is still attempted
        first for the unprivileged case.
        """
        if self._pid is None:
            return
        try:
            os.kill(self._pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        self._hangup()

    def _hangup(self) -> None:
        if self._master is not None:
            try:
                os.close(self._master)
            except OSError:
                pass
            self._master = None

    def _drain(self) -> None:
        if self._master is None:
            return
        try:
            chunk = os.read(self._master, 65536)
        except OSError:
            # EIO is how Linux reports "the last slave fd closed", i.e. the
            # child is gone. It is the normal end of a run, not a failure.
            chunk = b""
        if not chunk:
            self._reap()
            return
        self._check_echo()
        self.output.emit(chunk.decode("utf-8", "replace"))

    def _check_echo(self) -> None:
        """Track the slave's ECHO flag; master and slave share it on Linux."""
        if self._master is None:
            return
        try:
            echo_on = bool(termios.tcgetattr(self._master)[3] & termios.ECHO)
        except (OSError, termios.error):
            return
        if echo_on == self._secret:      # i.e. the state changed
            self._secret = not echo_on
            self.secret_input.emit(self._secret)

    def _reap(self) -> None:
        if self._notifier is not None:
            self._notifier.setEnabled(False)
            self._notifier = None
        self._hangup()

        code = -1
        if self._pid is not None:
            try:
                _, status = os.waitpid(self._pid, 0)
                if os.WIFEXITED(status):
                    code = os.WEXITSTATUS(status)
                elif os.WIFSIGNALED(status):
                    code = -1
            except ChildProcessError:
                pass
        self._pid = None
        if self._secret:
            self._secret = False
            self.secret_input.emit(False)
        self.finished.emit(code, exit_meaning(code, self._command))
