"""C4: MCP server ``capability_mentions`` flow into tool capabilities.

C4 (REFACTOR_PLAN.md Lote C): the ``MCPServerConfig`` schema gains a
``capability_mentions`` field.  When :class:`MCPToolWrapper` is
instantiated, it captures the per-server tags and exposes them via
``get_capabilities()`` (alongside the always-on ``network`` tag).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from femtobot.agent.tools.mcp import MCPToolWrapper

pytestmark = pytest.mark.architecture


def _make_wrapper(mentions: list[str] | None) -> MCPToolWrapper:
    """Build a wrapper without performing an MCP connect.

    We bypass ``__init__`` and assign the few attributes ``get_capabilities``
    reads, since the real ctor needs a live ``ClientSession``.  Tests
    don't exercise ``execute()``.
    """
    wrapper = MCPToolWrapper.__new__(MCPToolWrapper)
    wrapper._name = "mcp_test_tool"  # type: ignore[attr-defined]
    wrapper._server_name = "test"  # type: ignore[attr-defined]
    wrapper._capability_mentions = list(mentions or [])  # type: ignore[attr-defined]
    return wrapper


def test_capability_mentions_none_adds_only_network() -> None:
    """C4: an empty ``capability_mentions`` produces only ``network`` (C4)."""
    wrapper = _make_wrapper([])
    assert wrapper.get_capabilities() == ["network"]


def test_capability_mentions_appear_after_network() -> None:
    """C4: declared mentions come after ``network`` in stable order (C4)."""
    wrapper = _make_wrapper(["long-running", "needs-confirmation"])
    caps = wrapper.get_capabilities()
    # network first, then mentions in order, no duplicates.
    assert caps[0] == "network"
    assert "long-running" in caps
    assert "needs-confirmation" in caps


def test_capability_mentions_deduped() -> None:
    """C4: ``network`` listed twice is deduped (C4)."""
    wrapper = _make_wrapper(["network", "long-running"])
    caps = wrapper.get_capabilities()
    assert caps.count("network") == 1
    assert caps.count("long-running") == 1


def test_capability_mentions_dedupes_blank_entries() -> None:
    """C4: empty strings in ``capability_mentions`` are dropped (C4)."""
    wrapper = _make_wrapper(["", "long-running", ""])
    caps = wrapper.get_capabilities()
    assert "" not in caps
    assert "long-running" in caps
    assert "network" in caps


def test_mcp_server_config_accepts_capability_mentions() -> None:
    """C4: ``MCPServerConfig`` schema accepts ``capability_mentions`` (C4)."""
    from femtobot.config.schema import MCPServerConfig

    cfg = MCPServerConfig(
        command="mcp-server",
        args=[],
        capability_mentions=["long-running", "stateful"],
    )
    assert cfg.capability_mentions == ["long-running", "stateful"]


def test_mcp_server_config_defaults_to_empty_list() -> None:
    """C4: default ``capability_mentions`` is an empty list (C4)."""
    from femtobot.config.schema import MCPServerConfig

    cfg = MCPServerConfig(command="mcp-server")
    assert cfg.capability_mentions == []


def test_mcp_wrapper_constructor_stores_capability_mentions() -> None:
    """C4: the constructor stores the mentions even when other kwargs vary (C4)."""
    # Use a stubbed ``session`` and ``tool_def``; we only need the
    # constructor to run and record ``_capability_mentions`` correctly.
    fake_session = SimpleNamespace()
    fake_tool = SimpleNamespace(
        name="some_tool",
        description="...",
        inputSchema={"type": "object", "properties": {}},
    )
    wrapper = MCPToolWrapper(
        fake_session,  # type: ignore[arg-type]
        "server_a",
        fake_tool,  # type: ignore[arg-type]
        capability_mentions=["long-running"],
    )
    assert wrapper._capability_mentions == ["long-running"]  # type: ignore[attr-defined]
    # ``network`` is always present.
    assert "network" in wrapper.get_capabilities()
