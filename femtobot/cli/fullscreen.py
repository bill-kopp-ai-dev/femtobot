"""Fullscreen alt-screen mode for the Femtobot CLI.

Inspired by Claude Code's automatic alt-screen detection:
FEMTOBOT_CLI_REFACTOR_PLAN.md Camada 3, T3.5.

The alt-screen escape sequences:
  Enter:  sys.stdout.write("\\x1b[?1049h")
  Exit:   sys.stdout.write("\\x1b[?1049l")

These switch to a separate terminal buffer so the app can redraw
cleanly without scrolling artifacts.

Detection:
  - Manual: /fullscreen toggle command
  - Auto: shutil.get_terminal_size() < threshold (80x24)
  - Safe: must be a real TTY (not pipe/cat/redirect)

Usage:
    from femtobot.cli.fullscreen import AltScreenManager

    manager = AltScreenManager()
    manager.enter()    # switch to alt screen
    # ... render app ...
    manager.exit()     # return to normal screen
"""

from __future__ import annotations

import shutil
import sys
from contextlib import contextmanager
from typing import Generator

MIN_TERMINAL_WIDTH = 80
MIN_TERMINAL_HEIGHT = 24


class AltScreenManager:
    """Manages entry/exit from the terminal's alternate screen buffer."""

    ENTER_ESCAPE = "\x1b[?1049h"
    EXIT_ESCAPE = "\x1b[?1049l"
    CURSOR_SHOW = "\x1b[?25h"
    CURSOR_HIDE = "\x1b[?25l"

    def __init__(self, out=None):
        self._out = out or sys.stdout
        self._entered = False

    def _write(self, seq: str) -> None:
        try:
            self._out.write(seq)
            self._out.flush()
        except OSError:
            pass  # pipe/closed stdout

    def is_tty(self) -> bool:
        """True if stdout is a real terminal (not a pipe or redirect)."""
        try:
            return self._out.isatty()
        except Exception:
            return False

    def should_auto_enter(self) -> bool:
        """True if terminal is too small and auto mode is enabled."""
        try:
            w, h = shutil.get_terminal_size()
            return w < MIN_TERMINAL_WIDTH or h < MIN_TERMINAL_HEIGHT
        except Exception:
            return False

    def enter(self) -> None:
        """Switch to the alternate screen buffer."""
        if self._entered:
            return
        if not self.is_tty():
            return
        self._write(self.CURSOR_HIDE)
        self._write(self.ENTER_ESCAPE)
        self._entered = True

    def exit(self) -> None:
        """Return to the normal screen buffer."""
        if not self._entered:
            return
        self._write(self.EXIT_ESCAPE)
        self._write(self.CURSOR_SHOW)
        self._entered = False

    @property
    def is_active(self) -> bool:
        return self._entered

    @contextmanager
    def session(self) -> Generator[None, None, None]:
        """Context manager: enter on __enter__, exit on __exit__."""
        self.enter()
        try:
            yield
        finally:
            self.exit()


def is_small_terminal() -> bool:
    """Check if current terminal is smaller than minimum threshold."""
    try:
        w, h = shutil.get_terminal_size()
        return w < MIN_TERMINAL_WIDTH or h < MIN_TERMINAL_HEIGHT
    except Exception:
        return False


def supports_alt_screen() -> bool:
    """Check if stdout supports alt-screen (is a real TTY)."""
    try:
        return sys.stdout.isatty()
    except Exception:
        return False
