"""femtobot.cli — CLI surface for the femtobot project.

The implementation lives in :mod:`femtobot.cli.commands` (a slim
Typer wrapper around the in-REPL agent loop) and
:mod:`femtobot.cli._nanobot_mirror` (the byte-for-byte mirror of
``nanobot/cli/stream.py``). These re-exports preserve import sites
that pre-date 0.1.0-cli.1.

Public symbols exposed:

  - ``app`` — the root Typer application. Use via ``python -m
    femtobot.cli`` or the ``femtobot`` entry-point.
  - ``StreamRenderer`` / ``ThinkingSpinner`` / ``_make_console`` —
    re-exported from the mirror so user code importing
    ``from femtobot.cli.stream import StreamRenderer`` keeps working
    after the parity layer was deleted in 0.1.0-cli.1.

Note: the ``agent_app`` / ``gateway_app`` / ``sessions_app`` /
``mcp_app`` symbols that nanobot exposes are **not** part of
femtobot's CLI surface (femtobot uses ``app.command()`` decorators
on the root Typer rather than nested sub-apps). They live in
:mod:`femtobot.cli.commands` if you need them at runtime.
"""

from __future__ import annotations

from femtobot.cli._nanobot_mirror.stream import (  # noqa: F401
    StreamRenderer,
    ThinkingSpinner,
    _make_console,
)

__all__ = [
    "StreamRenderer",
    "ThinkingSpinner",
    "_make_console",
]
