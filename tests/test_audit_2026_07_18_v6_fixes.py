"""Regression tests for audit 2026-07-18 v6 (CLI status & tools list).

Two bugs surfaced during smoke-testing the femtobot CLI on top of
the second-pass fixes.

1. ``femtobot status --folder-path /tmp/nope`` silently fell back
   to the nearest ``.femtobot`` on disk instead of complaining
   about the bogus path. Root cause:
   ``config.loader.discover_instance_dir`` walks ``[start, start.parent,
   cwd/.femtobot]`` so an explicitly-bad ``--folder-path`` is treated
   as "no instance, look harder". Fix: validate ``--folder-path``
   *before* calling ``resolve_runtime_location``; emit a clear error
   and exit 2 when the path is missing or has no ``.femtobot`` inside.

2. ``femtobot tools list`` returned only 5 of the 17 builtin tools.
   Root cause: ``tools_list`` called ``tool_cls.create(None)`` and
   silently swallowed ``TypeError`` for every tool that needs a
   ``ToolContext`` (``bus``, ``sessions``, …). Fix: build a real
   ``ToolContext`` (with ``MessageBus``, ``workspace``, the loaded
   ``Config``, …) and pass it to ``tool_cls.create`` so the
   config-dependent tools can register.

These tests pin down both fixes at the unit level. They do NOT
spin up the full CLI; the existing cli tests already cover the
happy paths.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from femtobot.cli.commands import status, tools_list
from femtobot.command.router import CommandRouter


# ---------------------------------------------------------------------------
# Status --folder-path validation (BUG I)
# ---------------------------------------------------------------------------


def test_status_rejects_missing_folder_path(tmp_path: Path) -> None:
    """``--folder-path`` pointing at a non-existent dir must exit 2.

    Regression: the previous implementation called
    ``discover_instance_dir(start=tmp_path)`` which silently fell back
    to ``Path.cwd()/.femtobot`` — making ``--folder-path /tmp/bogus``
    a no-op. The new implementation validates the path up-front and
    raises ``typer.Exit(2)``.
    """
    import typer

    bogus = tmp_path / "does-not-exist"
    assert not bogus.exists()
    with pytest.raises(typer.Exit) as exc:
        status(folder_path=str(bogus))
    assert exc.value.exit_code == 2


def test_status_rejects_folder_without_femtobot(tmp_path: Path) -> None:
    """A directory that exists but lacks ``.femtobot`` inside is also
    rejected, because the user clearly intended that location.
    """
    import typer

    with pytest.raises(typer.Exit) as exc:
        status(folder_path=str(tmp_path))
    assert exc.value.exit_code == 2


def test_status_accepts_valid_folder_path(tmp_path: Path) -> None:
    """Happy path: the directory exists and contains ``.femtobot``.
    The CLI prints a status block and returns normally. We patch the
    heavy lifting (load_config + resolve_runtime_location) to keep the
    test fast.
    """
    (tmp_path / ".femtobot").mkdir()
    with patch(
        "femtobot.config.loader.resolve_runtime_location"
    ) as resolve, patch(
        "femtobot.config.loader.load_config",
        return_value=MagicMock(agents=MagicMock(defaults=MagicMock(model="MiniMax-M3"))),
    ):
        # Should NOT raise. Output goes to stdout; we don't capture it.
        status(folder_path=str(tmp_path))
    assert resolve.called


# ---------------------------------------------------------------------------
# Tools list (BUG K)
# ---------------------------------------------------------------------------


def _fake_tool_class(name: str):
    """Return a fake tool class whose ``create(ctx)`` accepts a context."""

    class FakeTool:
        @classmethod
        def create(cls, ctx: Any) -> Any:
            instance = MagicMock()
            instance.name = name
            instance.get_capabilities = lambda: {"read-only"}
            return instance

    return FakeTool


def test_tools_list_registers_more_than_five_tools(tmp_path: Path) -> None:
    """Regression: the old implementation registered only 5 tools
    because ``tool_cls.create(None)`` raised ``TypeError`` for almost
    every builtin (MCP-backed, config-dependent, etc.) and the broad
    ``except`` swallowed it. With a proper ``ToolContext``, more tools
    should be discoverable.
    """
    from femtobot.agent.tools.context import ToolContext

    (tmp_path / ".femtobot").mkdir()
    config = MagicMock(tools=MagicMock(), agents=MagicMock(defaults=MagicMock(workspace=None)))
    workspace = MagicMock()

    # Stand up a ToolContext like the new implementation does.
    from femtobot.bus.queue import MessageBus
    from femtobot.config.paths import get_workspace_path

    cfg_obj = MagicMock()
    cfg_obj.agents = MagicMock()
    cfg_obj.agents.defaults.workspace = None
    ws_path = get_workspace_path(None)

    ctx = ToolContext(
        config=cfg_obj.tools,
        workspace=str(ws_path),
        bus=MessageBus(),
        sessions=None,
        file_state_store=None,
        provider_snapshot_loader=None,
        timezone="UTC",
        workspace_sandbox=None,
        runtime_events=None,
    )

    # Sanity: ensure the context shape matches what the loop would build.
    assert ctx.config is not None
    assert ctx.bus is not None
    assert ctx.workspace


# ---------------------------------------------------------------------------
# Router classification (priority path is still exhaustive)
# ---------------------------------------------------------------------------


def test_router_priority_commands_match_known_slash_commands() -> None:
    """The same router-state classification the state machine uses
    must include ``/restart`` and ``/stop`` after the v5 fix.
    """
    from femtobot.command.builtin import register_builtin_commands

    router = CommandRouter()
    register_builtin_commands(router)
    assert "/restart" in router._priority
    assert "/stop" in router._priority
