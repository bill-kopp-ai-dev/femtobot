"""Tests for tool-hint capability tags and the MCP side-channel cache.

Refs: FEMTOBOT_MCP_IMPROVEMENT_PLAN.md Fase 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from femtobot.agent.tools import mcp as mcp_tools
from femtobot.agent.tools.mcp import (
    _clear_connected_cache,
    _update_connected_cache,
    get_connected_servers,
)
from femtobot.utils.tool_hints import (
    _fmt_mcp,
    _strip_mcp_tool_prefix,
    get_mcp_tool_metadata,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _FakeToolCall:
    """Minimal stand-in for ``ToolCallRequest`` used by ``_fmt_mcp``."""

    name: str
    arguments: Any = None


@pytest.fixture(autouse=True)
def _reset_mcp_cache() -> None:
    """Each test gets a clean MCP cache; failure to isolate leaks across tests."""
    _clear_connected_cache()


# ---------------------------------------------------------------------------
# Phase 2.1 — get_mcp_tool_metadata
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("wrapped", "bare"),
    [
        # Double-underscore separator: exact split works.
        ("mcp_agy_mcp_server__agy_health", "agy_health"),
        # Single-word server: works.
        ("mcp_agy_agy_run_task", "agy_run_task"),
        # No prefix: passes through.
        ("agy_run_task", "agy_run_task"),
    ],
)
def test_strip_mcp_tool_prefix(wrapped: str, bare: str) -> None:
    """The prefix-stripping helper is best-effort; document its real behavior."""
    assert _strip_mcp_tool_prefix(wrapped) == bare


def test_strip_mcp_tool_prefix_known_caveat_multi_word_server() -> None:
    """Multi-word server (after sanitization) is ambiguous.

    ``mcp_agy_mcp_server_agy_run_task`` could be parsed as
    ``mcp_<agy>_<mcp_server_agy_run_task>`` (what the helper returns)
    or ``mcp_<agy_mcp_server>_<agy_run_task>`` (the canonical intent).

    The capability-tag lookup uses suffix matching
    (:func:`get_mcp_tool_metadata`) precisely to sidestep this ambiguity,
    so the prefix-strip helper's imprecision is OK in practice.
    """
    # The helper returns the imperfect split (single-word server).
    assert (
        _strip_mcp_tool_prefix("mcp_agy_mcp_server_agy_run_task")
        == "mcp_server_agy_run_task"
    )
    # But suffix matching still finds the right capability tag.
    assert get_mcp_tool_metadata("mcp_agy_mcp_server_agy_run_task") == (
        "long-running",
        "safe-mode:confirm",
    )


def test_get_mcp_tool_metadata_returns_long_running_tag() -> None:
    """``agy_run_task`` and ``claude_run_task`` carry the long-running + confirm tags."""
    assert ("long-running", "safe-mode:confirm") == get_mcp_tool_metadata(
        "mcp_agy_mcp_server_agy_run_task"
    )
    assert ("long-running", "safe-mode:confirm") == get_mcp_tool_metadata(
        "mcp_claude_code_cli_mcp_claude_run_task"
    )


def test_get_mcp_tool_metadata_returns_read_only_for_health() -> None:
    """Health-check tools advertise cheap + read-only."""
    assert get_mcp_tool_metadata("mcp_agy_mcp_server_agy_health") == ("read-only", "cheap")


def test_get_mcp_tool_metadata_empty_for_unknown_tool() -> None:
    """Unknown tools get an empty tuple (no tags == no special hints)."""
    assert get_mcp_tool_metadata("mcp_unknown_server_xyz") == ()


# ---------------------------------------------------------------------------
# Phase 2.2 — _fmt_mcp includes capability tags
# ---------------------------------------------------------------------------


def test_fmt_mcp_includes_tags_for_long_running_tool() -> None:
    """A long-running tool call renders with the tag suffix in brackets."""
    tc = _FakeToolCall(
        name="mcp_agy_mcp_server_agy_run_task",
        arguments={"workspace_path": "/tmp/proj"},
    )
    out = _fmt_mcp(tc)
    # The hint ends with the capability tag suffix in brackets.
    assert "[long-running, safe-mode:confirm]" in out
    # The bare tool name is embedded somewhere in the output.
    assert "agy_run_task" in out
    # The arg (workspace_path) is abbreviated into the hint.
    assert "/tmp/proj" in out


def test_fmt_mcp_includes_tags_even_without_args() -> None:
    """Tags are emitted even when the call has no string argument."""
    tc = _FakeToolCall(name="mcp_agy_mcp_server_agy_run_task", arguments={})
    out = _fmt_mcp(tc)
    assert "[long-running, safe-mode:confirm]" in out
    assert "agy_run_task" in out


def test_fmt_mcp_no_tags_for_unknown_tool() -> None:
    """Unknown MCP tools render without a tag suffix (back-compat)."""
    tc = _FakeToolCall(
        name="mcp_custom_server_unknown_tool",
        arguments={"foo": "/tmp/x"},
    )
    out = _fmt_mcp(tc)
    assert "unknown_tool" in out
    assert "[" not in out  # no tag suffix
    assert "custom" in out  # server prefix is still mentioned


# ---------------------------------------------------------------------------
# Phase 2.4 — Side-channel cache
# ---------------------------------------------------------------------------


def test_get_connected_servers_starts_empty() -> None:
    """The autouse fixture clears the cache; baseline is empty."""
    assert get_connected_servers() == {}


def test_update_and_read_connected_cache() -> None:
    """Updating the cache populates ``get_connected_servers`` sorted."""
    _update_connected_cache("agy-mcp-server", ["mcp_agy_mcp_server_agy_run_task", "mcp_agy_mcp_server_agy_health"])
    snapshot = get_connected_servers()
    assert "agy-mcp-server" in snapshot
    # Sorted alphabetically.
    assert snapshot["agy-mcp-server"] == [
        "mcp_agy_mcp_server_agy_health",
        "mcp_agy_mcp_server_agy_run_task",
    ]


def test_clear_connected_cache_specific_server() -> None:
    """Clearing one server leaves the others intact."""
    _update_connected_cache("agy-mcp-server", ["mcp_agy_mcp_server_agy_health"])
    _update_connected_cache("claude-code-cli-mcp", ["mcp_claude_code_cli_mcp_claude_health"])
    _clear_connected_cache("agy-mcp-server")
    assert "agy-mcp-server" not in get_connected_servers()
    assert "claude-code-cli-mcp" in get_connected_servers()


def test_clear_connected_cache_all() -> None:
    """``_clear_connected_cache(None)`` empties the whole cache."""
    _update_connected_cache("agy-mcp-server", ["x"])
    _update_connected_cache("claude-code-cli-mcp", ["y"])
    _clear_connected_cache(None)
    assert get_connected_servers() == {}


def test_get_connected_servers_returns_independent_copy() -> None:
    """Mutating the returned snapshot must not affect the internal cache."""
    _update_connected_cache("agy-mcp-server", ["mcp_agy_mcp_server_agy_run_task"])
    snapshot = get_connected_servers()
    snapshot["agy-mcp-server"].append("rogue")
    # Re-read: internal cache is untouched.
    assert get_connected_servers()["agy-mcp-server"] == [
        "mcp_agy_mcp_server_agy_run_task"
    ]


# ---------------------------------------------------------------------------
# Phase 2.3 — Capability block in system prompt
# ---------------------------------------------------------------------------


def test_mcp_capability_block_empty_when_no_servers(tmp_path) -> None:
    """With no connected MCPs, the capability block is empty."""
    from femtobot.agent.context import ContextBuilder

    block = ContextBuilder._build_mcp_capability_block()
    assert block == ""


def test_mcp_capability_block_lists_connected_servers(tmp_path) -> None:
    """When servers are connected, the block lists them with capability tags."""
    from femtobot.agent.context import ContextBuilder

    _update_connected_cache(
        "agy-mcp-server",
        ["mcp_agy_mcp_server_agy_run_task", "mcp_agy_mcp_server_agy_health"],
    )
    _update_connected_cache(
        "claude-code-cli-mcp",
        ["mcp_claude_code_cli_mcp_claude_run_task"],
    )

    block = ContextBuilder._build_mcp_capability_block()
    assert "## MCP Servers in this workspace" in block
    assert "### agy-mcp-server" in block
    assert "### claude-code-cli-mcp" in block
    assert "[long-running, safe-mode:confirm]" in block
    assert "[read-only, cheap]" in block


def test_mcp_capability_block_appears_in_build_system_prompt(tmp_path) -> None:
    """The capability block is appended to the system prompt when servers are connected."""
    from femtobot.agent.context import ContextBuilder

    _update_connected_cache(
        "agy-mcp-server",
        ["mcp_agy_mcp_server_agy_run_task"],
    )

    cb = ContextBuilder(tmp_path)
    prompt = cb.build_system_prompt()
    assert "## MCP Servers in this workspace" in prompt
    assert "agy_run_task" in prompt
    assert "[long-running, safe-mode:confirm]" in prompt


def test_mcp_capability_block_absent_without_servers(tmp_path) -> None:
    """No MCP servers connected → no capability block in the system prompt."""
    from femtobot.agent.context import ContextBuilder

    cb = ContextBuilder(tmp_path)
    prompt = cb.build_system_prompt()
    assert "## MCP Servers in this workspace" not in prompt
