"""Mouse support for the Femtobot CLI.

Inspired by Claude Code mouse selection:
FEMTOBOT_CLI_REFACTOR_PLAN.md Camada 3, T3.4.

MVP: enable basic mouse events via prompt_toolkit's mouse_support.
This makes pickers (/model, /theme, /plugin) respond to mouse
click/hover. Full transcript mouse support is out of scope (mouse
in terminal scrollback = UX conflict).

Usage:
    from femtobot.cli.mouse import enable_mouse, disable_mouse

    enable_mouse()   # writes \\x1b[?1000h
    disable_mouse()  # writes \\x1b[?1000l

Or use the module-level constants for escape sequences directly.
"""

from __future__ import annotations

import sys
from typing import TextIO

# Mouse tracking escape sequences (DECSET/DECRST).
# ?9  — Mouse click reporting (legacy, x10)
# ?1000 — Mouse click + drag (modern, recommended)
# ?1002 — Mouse drag
# ?1006 — SGR mode (extended coordinates, better than legacy)
ENABLE_MOUSE = "\x1b[?1000h"
ENABLE_MOUSE_EXTENDED = "\x1b[?1006h"
DISABLE_MOUSE = "\x1b[?1000l"
DISABLE_MOUSE_EXTENDED = "\x1b[?1006l"


def enable_mouse(out: TextIO = sys.stdout, extended: bool = True) -> bool:
    """Enable mouse tracking on the given output stream.

    Args:
        out: The output stream to write the escape sequence to.
            Defaults to sys.stdout.
        extended: If True, uses SGR mode (?1006) which is more reliable
            than legacy DECSET (?9).

    Returns:
        True if the escape sequence was written successfully, False
        if the stream is not a TTY or writing failed.
    """
    try:
        if not out.isatty():
            return False
        seq = ENABLE_MOUSE_EXTENDED if extended else ENABLE_MOUSE
        out.write(seq)
        out.flush()
        return True
    except (OSError, AttributeError):
        return False


def disable_mouse(out: TextIO = sys.stdout, extended: bool = True) -> bool:
    """Disable mouse tracking on the given output stream."""
    try:
        if not out.isatty():
            return False
        seq = DISABLE_MOUSE_EXTENDED if extended else DISABLE_MOUSE
        out.write(seq)
        out.flush()
        return True
    except (OSError, AttributeError):
        return False


def is_mouse_supported(out: TextIO = sys.stdout) -> bool:
    """Check if the terminal supports mouse tracking (is a real TTY)."""
    try:
        return out.isatty()
    except Exception:
        return False
