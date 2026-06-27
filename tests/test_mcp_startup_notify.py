"""Tests for the proactive MCP startup-failure notification (Phase 6).

Refs: FEMTOBOT_MCP_IMPROVEMENT_PLAN.md Fase 6.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from femtobot.bus.events import OutboundMessage
from femtobot.config.schema import AgentDefaults


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_loop(
    configured: list[str] | None = None,
    connected: list[str] | None = None,
    notify: bool = False,
) -> SimpleNamespace:
    """Build a stand-in AgentLoop with the attributes ``_connect_mcp`` reads."""
    loop = SimpleNamespace()
    loop._mcp_servers = {name: object() for name in (configured or [])}
    loop._mcp_stacks = {name: object() for name in (connected or [])}
    # ``agent_context.connect_mcp`` accesses ``self.tools`` — provide an empty
    # registry stand-in.
    loop.tools = MagicMock()

    defaults = AgentDefaults(notify_mcp_startup_failures=notify)
    loop.agents_config = SimpleNamespace(defaults=defaults)

    loop.bus = MagicMock()
    loop.bus.publish_outbound = AsyncMock()
    return loop


# ---------------------------------------------------------------------------
# Schema flag
# ---------------------------------------------------------------------------


def test_agent_defaults_notify_mcp_startup_failures_defaults_false() -> None:
    """The flag defaults to False to preserve the pre-Phase-6 behavior."""
    defaults = AgentDefaults()
    assert defaults.notify_mcp_startup_failures is False


def test_agent_defaults_notify_mcp_startup_failures_can_be_set_true() -> None:
    """The flag can be enabled explicitly via the config schema."""
    defaults = AgentDefaults(notify_mcp_startup_failures=True)
    assert defaults.notify_mcp_startup_failures is True


# ---------------------------------------------------------------------------
# _connect_mcp behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_mcp_no_warnings_when_all_servers_connected() -> None:
    """If every configured server is connected, no warning is published."""
    from femtobot.agent.loop import AgentLoop

    loop = _make_loop(
        configured=["agy-mcp-server", "claude-code-cli-mcp"],
        connected=["agy-mcp-server", "claude-code-cli-mcp"],
        notify=True,
    )

    # Call the method directly (skipping the agent_context.connect_mcp step).
    # We monkeypatch it to a no-op so the test doesn't depend on MCP machinery.
    with patch_agent_context_connect(loop):
        await AgentLoop._connect_mcp(loop)  # type: ignore[arg-type]

    loop.bus.publish_outbound.assert_not_awaited()


@pytest.mark.asyncio
async def test_connect_mcp_logs_but_silent_when_notify_disabled() -> None:
    """Default behavior: log warning, but DO NOT publish to user (back-compat)."""
    from femtobot.agent.loop import AgentLoop

    loop = _make_loop(
        configured=["agy-mcp-server", "claude-code-cli-mcp"],
        connected=["agy-mcp-server"],
        notify=False,  # default
    )

    with patch_agent_context_connect(loop):
        await AgentLoop._connect_mcp(loop)  # type: ignore[arg-type]

    loop.bus.publish_outbound.assert_not_awaited()


@pytest.mark.asyncio
async def test_connect_mcp_publishes_warning_when_notify_enabled() -> None:
    """With the flag enabled, missing servers trigger an outbound warning."""
    from femtobot.agent.loop import AgentLoop

    loop = _make_loop(
        configured=["agy-mcp-server", "claude-code-cli-mcp"],
        connected=["agy-mcp-server"],  # claude failed
        notify=True,
    )

    with patch_agent_context_connect(loop):
        await AgentLoop._connect_mcp(loop)  # type: ignore[arg-type]

    loop.bus.publish_outbound.assert_awaited_once()
    msg: OutboundMessage = loop.bus.publish_outbound.await_args.args[0]
    assert msg.channel == "cli"
    assert msg.chat_id == "startup"
    assert "claude-code-cli-mcp" in msg.content
    assert "/mcp reload" in msg.content


@pytest.mark.asyncio
async def test_connect_mcp_handles_missing_agents_config_gracefully() -> None:
    """If ``agents_config`` is absent or unreadable, default to silent."""
    from femtobot.agent.loop import AgentLoop

    loop = _make_loop(
        configured=["agy-mcp-server"],
        connected=[],
        notify=False,
    )
    # Remove agents_config to test defensive fallback.
    del loop.agents_config

    with patch_agent_context_connect(loop):
        await AgentLoop._connect_mcp(loop)  # type: ignore[arg-type]

    # No crash; no publish (defaults are silent).
    loop.bus.publish_outbound.assert_not_awaited()


@pytest.mark.asyncio
async def test_connect_mcp_publish_error_does_not_break_startup() -> None:
    """A publish error must not propagate — startup must continue."""
    from femtobot.agent.loop import AgentLoop

    loop = _make_loop(
        configured=["agy-mcp-server"],
        connected=[],
        notify=True,
    )
    loop.bus.publish_outbound = AsyncMock(side_effect=RuntimeError("bus down"))

    with patch_agent_context_connect(loop):
        # Must not raise.
        await AgentLoop._connect_mcp(loop)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


from contextlib import contextmanager


@contextmanager
def patch_agent_context_connect(loop):
    """Bypass the real ``agent_context.connect_mcp`` so _connect_mcp can run."""
    import femtobot.agent.context as agent_context_mod

    original = agent_context_mod.connect_mcp
    agent_context_mod.connect_mcp = AsyncMock()
    try:
        yield
    finally:
        agent_context_mod.connect_mcp = original
