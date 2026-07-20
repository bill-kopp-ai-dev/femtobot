"""Mirror of the nanobot CLI for the femtobot package.

The CLI module is borrowed from ``nanobot`` (project sibling) and
adapted to use femtobot's bus, agent loop, and config. The full
mirror lives here so that downstream consumers can either import
the names directly (``from femtobot.cli._nanobot_mirror.stream
import StreamRenderer``) or re-export them via ``femtobot.cli``.

Removed (parity-only, not present in nanobot):
  - ParityStreamRenderer
  - SpinnerWithElapsed
  - render_header_bar / render_welcome_card
  - ui_parity=compat profile

Added (femtobot-specific):
  - ``_ui_parity_shim.block_if_compat``: hard-error (exit 64)
    when ``--ui compat`` is detected at the CLI.

Note: this package does NOT re-export Typer sub-apps (agent_app,
sessions_app, etc.). Those are femtobot-specific and live in
:mod:`femtobot.cli.commands` where they are defined as real
``typer.Typer`` instances — not the ``_MissingFemtobotFeature``
stubs that ``_adapters`` provides for ``nanobot`` symbols that
femtobot has not yet implemented. Importing them from here would
silently give you a stub, which is exactly the kind of
non-obvious divergence we want to avoid.
"""

from __future__ import annotations

from femtobot.cli._nanobot_mirror.stream import (
    StreamRenderer,
    ThinkingSpinner,
    _make_console,
)

__all__ = [
    "StreamRenderer",
    "ThinkingSpinner",
    "_make_console",
]
