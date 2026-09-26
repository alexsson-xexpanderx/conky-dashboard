"""Turning terminal output into something a QPlainTextEdit can show.

slackpkg writes for a terminal, not for a text widget, and two of its habits
produce garbage when the bytes are appended verbatim:

  * slackpkg+ draws its progress counter with
    ``printf "%3s%%\\b\\b\\b\\b"`` (slackpkgplus.sh:1214 and :1455).  Those are
    four literal backspaces, meant to rewind the cursor so the next percentage
    overwrites the last one in place.  A text widget has no cursor to rewind,
    so every percentage survives and each 0x08 is drawn as a box -- the
    ``2%****  4%****  7%****`` trail.

  * slackpkg+ defines ANSI colour escapes (slackpkgplus.sh:40-51) as plain
    variables with no tty check, so nothing stops them reaching a pipe.  They
    would render as literal ``[1;32m`` noise.

So the chunk is parsed into the three operations that actually matter --
insert text, rub out N characters, discard the current line -- and the caller
applies them to a real cursor.  Keeping it a pure function is deliberate: the
cursor arithmetic in app.py is hard to test, this is not.

Only the sequences slackpkg actually emits are handled.  This is not a
terminal emulator, and the day it needs to become one is the day to reach for
pyte instead.
"""

from __future__ import annotations

import re

# CSI (colour, cursor moves): ESC [ params intermediates final.
_CSI = r"\x1b\[[0-?]*[ -/]*[@-~]"
# OSC (window title): ESC ] ... terminated by BEL or ST.
_OSC = r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
# Escapes that are not CSI or OSC: ESC, optional intermediates, one final byte
# in 0x30-0x7E.  This has to be this wide because `tput sc` / `tput rc` emit
# ESC 7 and ESC 8 under xterm terminfo -- 0x37 and 0x38, outside the @-Z range
# a narrower pattern would cover.  core-functions.sh:65 and
# post-functions.sh:15 both use them.
_ESC2 = r"\x1b[ -/]*[0-~]"

_ESCAPE = re.compile(f"{_OSC}|{_CSI}|{_ESC2}")

# Kept as-is; every other C0 control character is dropped rather than drawn.
_KEEP = "\n\t"

TEXT = "text"
BACK = "back"
KILL = "kill"


def tokenize(chunk: str) -> list[tuple[str, object]]:
    """Split terminal output into ``(op, value)`` pairs.

    ``(TEXT, str)``  insert this text
    ``(BACK, int)``  rub out this many characters, stopping at column 0
    ``(KILL, None)`` carriage return: discard the current line

    Consecutive backspaces are coalesced, so the usual four-in-a-row arrive as
    one ``(BACK, 4)`` instead of four separate edits to the document.
    """
    chunk = _ESCAPE.sub("", chunk)

    ops: list[tuple[str, object]] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            ops.append((TEXT, "".join(buf)))
            buf.clear()

    i, end = 0, len(chunk)
    while i < end:
        ch = chunk[i]

        if ch == "\b":
            flush()
            if ops and ops[-1][0] == BACK:
                ops[-1] = (BACK, ops[-1][1] + 1)  # type: ignore[operator]
            else:
                ops.append((BACK, 1))

        elif ch == "\r":
            # CRLF is a line ending, not a carriage return -- treating it as
            # one would wipe the line just before its newline committed it.
            if i + 1 < end and chunk[i + 1] == "\n":
                buf.append("\n")
                i += 2
                continue
            flush()
            ops.append((KILL, None))

        elif ch in _KEEP or (ch >= " " and ch != "\x7f"):
            buf.append(ch)

        i += 1

    flush()
    return ops


def render(text: str, chunk: str) -> str:
    """Apply a chunk to plain text, the way the widget applies it to a cursor.

    Not used by the GUI -- app.py drives a QTextCursor so the document is
    edited in place -- but it pins down the semantics the cursor code has to
    match, and it is what the behaviour is checked against.
    """
    for op, value in tokenize(chunk):
        if op == TEXT:
            text += value
        elif op == BACK:
            column = len(text) - (text.rfind("\n") + 1)
            text = text[: len(text) - min(int(value), column)]
        elif op == KILL:
            text = text[: text.rfind("\n") + 1]
    return text
