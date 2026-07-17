"""Tests for the Live clear path (PR 2.1 of the longlogs plan).

The legacy ``_clear_current_line`` only erases one line, so when the
``Live`` occupies multiple rows (status, hint, footer), leftover lines
remain on screen and the next chunk of content interleaves with them.
``_clear_live_block`` is the new helper used after PR 2.2 wired the
elapsed-time ``Live`` into the ``ThinkingSpinner``.
"""

from __future__ import annotations

import io

from femtobot.cli.stream import _clear_live_block, _clear_current_line


class _TtyFile(io.StringIO):
    """A pseudo-TTY file that responds True to ``isatty``."""

    def isatty(self) -> bool:
        return True


class _NonTtyFile(io.StringIO):
    """A pseudo non-TTY file (captured log)."""

    def isatty(self) -> bool:
        return False


class _FakeConsole:
    def __init__(self, tty: bool) -> None:
        self.file = _TtyFile() if tty else _NonTtyFile()


def test_clear_live_block_tty_emits_screen_clear_escape():
    console = _FakeConsole(tty=True)
    _clear_live_block(console, height=4)
    written = console.file.getvalue()
    assert "\x1b[2J" in written
    assert "\x1b[H" in written
    # Should not emit raw newlines on a TTY — that would corrupt layout.
    assert "\n" not in written


def test_clear_live_block_non_tty_emits_only_newlines():
    console = _FakeConsole(tty=False)
    _clear_live_block(console, height=3)
    written = console.file.getvalue()
    assert "\n" in written
    assert written == "\n" * 3
    # Should not emit escape sequences to non-TTY consumers (#3265).
    assert "\x1b[" not in written


def test_clear_live_block_height_clamped_to_at_least_one():
    console = _FakeConsole(tty=False)
    _clear_live_block(console, height=0)
    assert console.file.getvalue() == "\n"


def test_clear_live_block_legacy_helper_still_works():
    """``_clear_current_line`` remains byte-compatible for callers that
    only need a single-line erase (e.g. legacy profile)."""
    console = _FakeConsole(tty=True)
    _clear_current_line(console)
    written = console.file.getvalue()
    assert written == "\r\x1b[2K"


def test_clear_live_block_non_tty_legacy_helper_no_op():
    """``_clear_current_line`` is a no-op on non-TTY (captured log)."""
    console = _FakeConsole(tty=False)
    _clear_current_line(console)
    assert console.file.getvalue() == ""
