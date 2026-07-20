"""Streaming renderer for CLI output — compatibility layer (D5).

The canonical implementation lives in
:mod:`femtobot.cli._nanobot_mirror.stream` (a verbatim copy of
``nanobot/cli/stream.py``). This module re-exports the symbols under
their stable ``femtobot.cli.stream.*`` paths so all user-facing
imports (``from femtobot.cli.stream import StreamRenderer``) keep
working unchanged.

The previous femtobot-parity variant (live-spawn in __init__,
ShowSpinnerWithElapsed, render_input_bar markup, etc.) was deleted
with the parity layer in 0.1.0-cli.1 — see
``docs/exec-plan-resolucao-bugs-longlogs.md`` and the migration
plan at ``plans/femtobot_nanobot_cli_migration/PLAN_*.md``.
"""

from __future__ import annotations

# Re-export the canonical nanobot mirror.
from femtobot.cli._nanobot_mirror.stream import (  # noqa: F401
    StreamRenderer,
    ThinkingSpinner,
)
from femtobot.cli._nanobot_mirror.stream import _make_console  # noqa: F401

__all__ = [
    "StreamRenderer",
    "ThinkingSpinner",
    "_make_console",
]
