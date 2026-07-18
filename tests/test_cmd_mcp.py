"""Tests for the ``/mcp`` slash command (Phase 5).

Refs: FEMTOBOT_MCP_IMPROVEMENT_PLAN.md Fase 5.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from femtobot.bus.events import InboundMessage, OutboundMessage
from femtobot.command.builtin import BUILTIN_COMMAND_SPECS, cmd_mcp
from femtobot.command.router import CommandContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_loop(
    configured: dict[str, object] | None = None,
    connected: dict[str, object] | None = None,
    tool_names: list[str] | None = None,
) -> MagicMock:
    """Build a stand-in AgentLoop exposing the attributes ``cmd_mcp`` reads."""
    loop = MagicMock()
    loop._mcp_servers = configured or {}
    loop._mcp_stacks = connected or {}
    tools = MagicMock()
    tools.tool_names = tool_names or []
    loop.tools = tools
    loop.bus = MagicMock()
    return loop


def _make_ctx(
    loop: MagicMock, args: str = "", content: str = ""
) -> CommandContext:
    """Build a CommandContext whose msg.content/args point to ``args``."""
    msg = InboundMessage(
        channel="cli",
        chat_id="test",
        sender_id="tester",
        content=content or args,
        metadata={},
    )
    return CommandContext(
        msg=msg,
        session=None,
        key="cli:test",
        raw="/mcp" if not args else f"/mcp {args}",
        args=args,
        loop=loop,
    )


def _content(ctx_result: OutboundMessage | None) -> str:
    """Pull the .content field out of the OutboundMessage (or fail)."""
    assert ctx_result is not None, "cmd_mcp returned None"
    return ctx_result.content


# ---------------------------------------------------------------------------
# Spec registration
# ---------------------------------------------------------------------------


def test_mcp_command_is_in_spec_palette() -> None:
    """``/mcp`` is listed in the command palette so UIs can surface it."""
    cmds = {spec.command: spec for spec in BUILTIN_COMMAND_SPECS}
    assert "/mcp" in cmds
    assert cmds["/mcp"].arg_hint  # has subcommand hint


# ---------------------------------------------------------------------------
# /mcp status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cmd_mcp_status_default() -> None:
    """``/mcp`` (no args) defaults to the status subcommand."""
    loop = _make_loop(
        configured={"agy-mcp-server": object(), "claude-code-cli-mcp": object()},
        connected={"agy-mcp-server": object()},
        tool_names=["read_file", "mcp_agy_mcp_server_agy_run_task"],
    )
    ctx = _make_ctx(loop, args="")

    out = await cmd_mcp(ctx)
    content = _content(out)
    assert "MCP server status:" in content
    assert "configured: agy-mcp-server, claude-code-cli-mcp" in content
    assert "connected:  agy-mcp-server" in content
    assert "missing:    claude-code-cli-mcp" in content
    assert "total tools registered: 2" in content


@pytest.mark.asyncio
async def test_cmd_mcp_status_no_mcps_configured() -> None:
    """No MCPs configured -> empty status block, no 'missing' line."""
    loop = _make_loop()
    ctx = _make_ctx(loop, args="status")

    out = await cmd_mcp(ctx)
    content = _content(out)
    assert "configured: (none)" in content
    assert "connected:  (none)" in content
    assert "missing" not in content


@pytest.mark.asyncio
async def test_cmd_mcp_status_all_connected() -> None:
    """All configured servers connected -> no 'missing' line."""
    loop = _make_loop(
        configured={"agy-mcp-server": object(), "claude-code-cli-mcp": object()},
        connected={"agy-mcp-server": object(), "claude-code-cli-mcp": object()},
        tool_names=[],
    )
    ctx = _make_ctx(loop, args="status")

    out = await cmd_mcp(ctx)
    content = _content(out)
    assert "missing" not in content


# ---------------------------------------------------------------------------
# /mcp reload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cmd_mcp_reload_invokes_request_mcp_reload() -> None:
    """``/mcp reload`` calls ``request_mcp_reload`` on the loop's bus."""
    loop = _make_loop()
    fake_result = {"message": "Reloaded 2 server(s)", "failed": []}

    with patch(
        "femtobot.agent.tools.mcp.request_mcp_reload",
        AsyncMock(return_value=fake_result),
    ) as mock_reload:
        ctx = _make_ctx(loop, args="reload")
        out = await cmd_mcp(ctx)

    mock_reload.assert_awaited_once_with(loop.bus)
    content = _content(out)
    assert "MCP reload:" in content
    assert "Reloaded 2 server(s)" in content


@pytest.mark.asyncio
async def test_cmd_mcp_reload_reports_failed_servers() -> None:
    """Failed servers are surfaced in the reload report."""
    loop = _make_loop()
    fake_result = {"message": "Reloaded 1 server(s)", "failed": ["claude-code-cli-mcp"]}

    with patch(
        "femtobot.agent.tools.mcp.request_mcp_reload",
        AsyncMock(return_value=fake_result),
    ):
        ctx = _make_ctx(loop, args="reload")
        out = await cmd_mcp(ctx)

    content = _content(out)
    assert "failed: claude-code-cli-mcp" in content


# ---------------------------------------------------------------------------
# /mcp tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cmd_mcp_tools_lists_prefix_filtered() -> None:
    """``/mcp tools <server>`` lists only tools matching that server prefix.

    Audit 2026-07-18 v3: ``_sanitize_name`` (femtobot.agent.tools.mcp)
    preserves hyphens in the server name, so tool prefixes come back as
    ``mcp_percival-osm_*`` (with hyphen). The slash command must match
    the server name verbatim — flattening ``-`` to ``_`` used to make
    real tools (e.g. ``mcp_percival-osm_*``) invisible to the lookup.
    """
    loop = _make_loop(
        tool_names=[
            "read_file",
            # Audit 2026-07-18 v3 fixture: tools with a hyphenated server
            # name. These were the ones the previous lookup missed.
            "mcp_percival-osm_osm_geocode",
            "mcp_percival-osm_osm_get_version",
            "mcp_claude_code_cli_mcp_claude_run_task",
        ]
    )
    ctx = _make_ctx(loop, args="tools percival-osm")

    out = await cmd_mcp(ctx)
    content = _content(out)
    assert "Tools from 'percival-osm':" in content
    assert "mcp_percival-osm_osm_geocode" in content
    assert "mcp_percival-osm_osm_get_version" in content
    assert "mcp_claude_code_cli_mcp_claude_run_task" not in content
    assert "read_file" not in content


@pytest.mark.asyncio
async def test_cmd_mcp_tools_matches_underscore_form_too() -> None:
    """Defensive: if a future ``_sanitize_name`` change flattens hyphens
    back to underscores, the slash command still resolves the server.
    """
    loop = _make_loop(
        tool_names=[
            "mcp_agy_mcp_server_agy_run_task",
            "mcp_agy_mcp_server_agy_health",
        ]
    )
    ctx = _make_ctx(loop, args="tools agy-mcp-server")
    out = await cmd_mcp(ctx)
    content = _content(out)
    assert "Tools from 'agy-mcp-server':" in content
    assert "mcp_agy_mcp_server_agy_run_task" in content


@pytest.mark.asyncio
async def test_cmd_mcp_tools_lists_zero_with_diagnostic_when_unknown() -> None:
    """When the server is unknown, the reply hints at the configured set."""
    loop = _make_loop(
        configured={"percival-osm": object()},
        tool_names=["mcp_percival-osm_osm_geocode"],
    )
    ctx = _make_ctx(loop, args="tools no-such-server")
    out = await cmd_mcp(ctx)
    content = _content(out)
    assert "No tools registered from 'no-such-server'" in content
    assert "Configured servers" in content
    assert "percival-osm" in content


@pytest.mark.asyncio
async def test_cmd_mcp_tools_no_match() -> None:
    """No tools registered from the named server -> explanatory message."""
    loop = _make_loop(tool_names=["read_file"])
    ctx = _make_ctx(loop, args="tools unknown-server")

    out = await cmd_mcp(ctx)
    content = _content(out)
    assert "No tools registered from 'unknown-server'." in content


@pytest.mark.asyncio
async def test_cmd_mcp_tools_usage_when_no_server() -> None:
    """``/mcp tools`` without a server -> usage hint."""
    loop = _make_loop()
    ctx = _make_ctx(loop, args="tools")

    out = await cmd_mcp(ctx)
    content = _content(out)
    assert "Usage:" in content
    assert "/mcp tools <server>" in content


# ---------------------------------------------------------------------------
# /mcp restart
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cmd_mcp_restart_invokes_request_mcp_reload() -> None:
    """``/mcp restart <server>`` triggers a hot-reload."""
    loop = _make_loop()
    fake_result = {"message": "Reloaded 1 server(s)", "failed": []}

    with patch(
        "femtobot.agent.tools.mcp.request_mcp_reload",
        AsyncMock(return_value=fake_result),
    ) as mock_reload:
        ctx = _make_ctx(loop, args="restart agy-mcp-server")
        out = await cmd_mcp(ctx)

    mock_reload.assert_awaited_once_with(loop.bus)
    content = _content(out)
    assert "MCP restart for 'agy-mcp-server':" in content


@pytest.mark.asyncio
async def test_cmd_mcp_restart_usage_when_no_server() -> None:
    """``/mcp restart`` without a server -> usage hint."""
    loop = _make_loop()
    ctx = _make_ctx(loop, args="restart")

    out = await cmd_mcp(ctx)
    content = _content(out)
    assert "Usage:" in content
    assert "/mcp restart <server>" in content


# ---------------------------------------------------------------------------
# Unknown subcommand
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cmd_mcp_unknown_subcommand() -> None:
    """Unknown subcommand -> error listing valid options."""
    loop = _make_loop()
    ctx = _make_ctx(loop, args="bogus")

    out = await cmd_mcp(ctx)
    content = _content(out)
    assert "Unknown /mcp subcommand" in content
    assert "bogus" in content
    assert "status|reload|tools <server>|restart <server>" in content


# ---------------------------------------------------------------------------
# Router dispatch
# ---------------------------------------------------------------------------


def test_mcp_registered_as_exact_and_prefix() -> None:
    """The /mcp command is registered in both exact and prefix tiers."""
    from femtobot.command.builtin import register_builtin_commands
    from femtobot.command.router import CommandRouter

    router = CommandRouter()
    register_builtin_commands(router)

    # ``/mcp`` (bare) is dispatched exactly.
    assert router.is_dispatchable_command("/mcp")
    # ``/mcp status`` is dispatched via prefix.
    assert router.is_dispatchable_command("/mcp status")
    assert router.is_dispatchable_command("/mcp tools agy-mcp-server")
    # Other commands untouched.
    assert not router.is_dispatchable_command("/mcp-something")
