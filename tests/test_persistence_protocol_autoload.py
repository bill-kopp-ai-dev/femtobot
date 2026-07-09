"""Tests for the persistence_protocol auto-load behavior (Phase 7).

Refs: FEMTOBOT_MCP_IMPROVEMENT_PLAN.md Fase 7.
"""

from __future__ import annotations

import pytest

from femtobot.agent.context import ContextBuilder
from femtobot.agent.tools import mcp as mcp_tools
from femtobot.agent.tools.mcp import (
    _PERSISTENCE_PROTOCOL_RE,
    _clear_connected_cache,
    cache_prompt_content,
    is_persistence_protocol_prompt,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_caches() -> None:
    """Both side-channel caches are emptied before each test."""
    _clear_connected_cache()
    for key in list(mcp_tools._PROMPT_CONTENT_CACHE):
        mcp_tools._PROMPT_CONTENT_CACHE.pop(key, None)


# ---------------------------------------------------------------------------
# Pattern matching
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "agy_persistence_protocol",
        "claude_persistence_protocol",
        "any_server_persistence_protocol",
    ],
)
def test_is_persistence_protocol_prompt_true_for_matching_names(name: str) -> None:
    """Names matching the pattern are detected as persistence_protocol prompts."""
    assert is_persistence_protocol_prompt(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "agy_run_task",
        "claude_run_task",
        "agy_health",
        "protocol",  # missing the trailing _persistence_protocol
        "persistence_protocol",  # missing server prefix
    ],
)
def test_is_persistence_protocol_prompt_false_for_non_matching_names(name: str) -> None:
    """Non-matching names are not flagged."""
    assert is_persistence_protocol_prompt(name) is False


def test_persistence_protocol_re_matches_real_world_names() -> None:
    """The exact prompt names exposed by the agy and claude servers match."""
    assert _PERSISTENCE_PROTOCOL_RE.match("agy_persistence_protocol")
    assert _PERSISTENCE_PROTOCOL_RE.match("claude_persistence_protocol")


# ---------------------------------------------------------------------------
# cache / get_cached_persistence_protocols
# ---------------------------------------------------------------------------


def test_cache_prompt_content_stores_under_tool_name() -> None:
    """Cached content is retrievable by exact tool name."""
    cache_prompt_content("agy_persistence_protocol", "Use workspace_path carefully.")
    assert (
        mcp_tools.get_prompt_content("agy_persistence_protocol")
        == "Use workspace_path carefully."
    )


def test_get_cached_persistence_protocols_filters_by_pattern() -> None:
    """Only prompts matching the ``*_persistence_protocol`` pattern are returned."""
    cache_prompt_content("agy_persistence_protocol", "AGY content")
    cache_prompt_content("claude_persistence_protocol", "CLAUDE content")
    cache_prompt_content("agy_unrelated", "AGY unrelated")  # not a protocol
    cache_prompt_content("agy_persistence_protocol_empty", "")  # empty content

    out = mcp_tools.get_cached_persistence_protocols()
    assert ("agy_persistence_protocol", "AGY content") in out
    assert ("claude_persistence_protocol", "CLAUDE content") in out
    assert ("agy_unrelated", "AGY unrelated") not in out
    # Empty-content prompts are also skipped.
    assert all(
        content for _, content in out
    ), "empty-content prompts should be filtered out"


def test_get_cached_persistence_protocols_returns_all_when_no_server() -> None:
    """When *server_name* is None, all cached prompts are returned."""
    cache_prompt_content("agy_persistence_protocol", "A")
    cache_prompt_content("claude_persistence_protocol", "C")
    out = mcp_tools.get_cached_persistence_protocols()
    assert ("agy_persistence_protocol", "A") in out
    assert ("claude_persistence_protocol", "C") in out


def test_get_cached_persistence_protocols_empty_when_no_cache() -> None:
    """Empty cache -> empty list."""
    assert mcp_tools.get_cached_persistence_protocols() == []


# ---------------------------------------------------------------------------
# System prompt integration
# ---------------------------------------------------------------------------


def test_mcp_protocol_block_empty_when_no_cache(tmp_path) -> None:
    """With nothing cached, the protocol block is empty (no system-prompt impact)."""
    assert ContextBuilder._build_mcp_protocol_block() == ""


def test_mcp_protocol_block_renders_cached_content(tmp_path) -> None:
    """Cached prompts render into the protocol block under their tool name."""
    cache_prompt_content(
        "agy_persistence_protocol",
        "Always pass workspace_path. confirm=true is gated.",
    )

    block = ContextBuilder._build_mcp_protocol_block()
    assert "## MCP Persistence Protocols" in block
    assert "agy_persistence_protocol" in block
    assert "Always pass workspace_path" in block


def test_mcp_protocol_block_bounds_content() -> None:
    """Large cached content is truncated to MAX_PROMPT_SNIPPET_CHARS."""
    huge = "X" * (mcp_tools.MAX_PROMPT_SNIPPET_CHARS * 5)
    cache_prompt_content("agy_persistence_protocol", huge)

    block = ContextBuilder._build_mcp_protocol_block()
    assert "X" * mcp_tools.MAX_PROMPT_SNIPPET_CHARS in block
    assert "X" * (mcp_tools.MAX_PROMPT_SNIPPET_CHARS + 1) not in block


def test_mcp_protocol_block_skips_empty_content() -> None:
    """Empty cached snippets are skipped, not emitted as empty headers."""
    cache_prompt_content("agy_persistence_protocol", "")
    block = ContextBuilder._build_mcp_protocol_block()
    # Should not even render the section when nothing meaningful exists.
    assert block == ""


def test_mcp_protocol_block_in_build_system_prompt(tmp_path) -> None:
    """When protocols are cached, the block appears in the system prompt."""
    cache_prompt_content("agy_persistence_protocol", "Use confirm=false first.")

    cb = ContextBuilder(tmp_path)
    prompt = cb.build_system_prompt()
    assert "## MCP Persistence Protocols" in prompt
    assert "Use confirm=false first." in prompt


def test_mcp_protocol_block_absent_without_cache(tmp_path) -> None:
    """No cached content -> no protocol section in the system prompt."""
    cb = ContextBuilder(tmp_path)
    prompt = cb.build_system_prompt()
    assert "## MCP Persistence Protocols" not in prompt
