"""Tests for the opt-in MCP persistence pointers (Phase 8).

Refs: FEMTOBOT_MCP_IMPROVEMENT_PLAN.md Fase 8.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from femtobot.agent.context import (
    ContextBuilder,
    _collect_mcp_persistence_snippets,
)
from femtobot.config.schema import AgentDefaults


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cfg(name: str, persistence_dir: Path | None) -> SimpleNamespace:
    """Build a stand-in MCPServerConfig exposing the ``env`` attr we need."""
    env: dict[str, str] = {}
    if persistence_dir is not None:
        # Use the convention ``AGY_MCP_PERSISTENCE_BASE_DIR`` (or any *...
        # _PERSISTENCE_BASE_DIR-shaped key).
        env["AGY_MCP_PERSISTENCE_BASE_DIR"] = str(persistence_dir)
    return SimpleNamespace(name=name, env=env)


# ---------------------------------------------------------------------------
# Schema flag
# ---------------------------------------------------------------------------


def test_agent_defaults_include_mcp_context_defaults_false() -> None:
    """Default off so existing installations don't grow their prompt."""
    assert AgentDefaults().include_mcp_context is False


def test_agent_defaults_include_mcp_context_can_be_set_true() -> None:
    """The flag can be enabled explicitly via the config schema."""
    assert AgentDefaults(include_mcp_context=True).include_mcp_context is True


# ---------------------------------------------------------------------------
# _collect_mcp_persistence_snippets — pure helper
# ---------------------------------------------------------------------------


def test_collect_empty_when_no_servers() -> None:
    """No MCPs configured -> empty string."""
    assert _collect_mcp_persistence_snippets(None) == ""
    assert _collect_mcp_persistence_snippets({}) == ""


def test_collect_skips_servers_without_persistence_dir_env(tmp_path: Path) -> None:
    """Servers without a ``*_PERSISTENCE_BASE_DIR`` env var are skipped."""
    cfg = SimpleNamespace(name="agy-mcp-server", env={"UNRELATED": "x"})
    assert _collect_mcp_persistence_snippets({"agy-mcp-server": cfg}) == ""


def test_collect_skips_missing_persistence_dir(tmp_path: Path) -> None:
    """A configured but non-existent directory is skipped without raising."""
    cfg = _make_cfg("agy-mcp-server", tmp_path / "does-not-exist")
    assert _collect_mcp_persistence_snippets({"agy-mcp-server": cfg}) == ""


def test_collect_reads_agents_md_and_memory_md(tmp_path: Path) -> None:
    """Existing AGENTS.md and MEMORY.md are read and prefixed with server name."""
    base = tmp_path / "open-cli-router" / "agy"
    base.mkdir(parents=True)
    (base / "AGENTS.md").write_text("# AGY agents\n\nPlan before you code.", encoding="utf-8")
    (base / "MEMORY.md").write_text("# Recent tasks\n\n- refactor X", encoding="utf-8")

    cfg = _make_cfg("agy-mcp-server", base)
    snippets = _collect_mcp_persistence_snippets({"agy-mcp-server": cfg})

    assert "### agy-mcp-server / AGENTS.md" in snippets
    assert "Plan before you code." in snippets
    assert "### agy-mcp-server / MEMORY.md" in snippets
    assert "- refactor X" in snippets


def test_collect_bounds_content(tmp_path: Path) -> None:
    """Content larger than the snippet cap is truncated, not fully embedded."""
    base = tmp_path / "agy"
    base.mkdir()
    big = "X" * 10_000
    (base / "AGENTS.md").write_text(big, encoding="utf-8")

    cfg = _make_cfg("agy-mcp-server", base)
    snippets = _collect_mcp_persistence_snippets({"agy-mcp-server": cfg})
    # Truncated to ~1500 chars; original 10k chars is way too large to fit.
    assert "X" * 1500 in snippets
    assert "X" * 5000 not in snippets


def test_collect_handles_missing_files_gracefully(tmp_path: Path) -> None:
    """An existing persistence dir without AGENTS.md/MEMORY.md returns empty."""
    base = tmp_path / "empty"
    base.mkdir()
    cfg = _make_cfg("agy-mcp-server", base)
    assert _collect_mcp_persistence_snippets({"agy-mcp-server": cfg}) == ""


def test_collect_continues_after_one_server_fails(tmp_path: Path) -> None:
    """A failing server does not block other servers from being read."""
    bad_base = tmp_path / "bad"
    bad_base.mkdir()
    # The path is in env but the dir was deleted before the call.
    bad_base.rmdir()
    cfg_bad = _make_cfg("agy-mcp-server", bad_base)

    good_base = tmp_path / "good"
    good_base.mkdir()
    (good_base / "AGENTS.md").write_text("# AGENTS OK", encoding="utf-8")
    cfg_good = _make_cfg("claude-code-cli-mcp", good_base)

    snippets = _collect_mcp_persistence_snippets(
        {"agy-mcp-server": cfg_bad, "claude-code-cli-mcp": cfg_good}
    )
    assert "claude-code-cli-mcp / AGENTS.md" in snippets
    assert "AGENTS OK" in snippets


# ---------------------------------------------------------------------------
# System prompt integration
# ---------------------------------------------------------------------------


def _make_context_builder(
    tmp_path: Path,
    *,
    include_mcp_context: bool,
    mcp_servers: dict | None,
) -> ContextBuilder:
    """Build a ContextBuilder with custom agents_config + tools_config."""
    defaults = AgentDefaults(include_mcp_context=include_mcp_context)
    cb = ContextBuilder(tmp_path)
    # Inject mock config objects so we don't need full AgentLoop wiring.
    cb.agents_config = SimpleNamespace(defaults=defaults)
    cb.tools_config = SimpleNamespace(mcp_servers=mcp_servers or {})
    return cb


def test_system_prompt_skips_mcp_block_when_flag_off(tmp_path: Path) -> None:
    """Default (flag off) -> no MCP persistence pointers in the prompt."""
    base = tmp_path / "agy"
    base.mkdir()
    (base / "AGENTS.md").write_text("should not appear", encoding="utf-8")

    cfg = _make_cfg("agy-mcp-server", base)
    cb = _make_context_builder(tmp_path, include_mcp_context=False, mcp_servers={"agy-mcp-server": cfg})

    prompt = cb.build_system_prompt()
    assert "## MCP Persistence Pointers" not in prompt
    assert "should not appear" not in prompt


def test_system_prompt_includes_mcp_block_when_flag_on(tmp_path: Path) -> None:
    """With flag on, the configured MCP's headers are injected."""
    base = tmp_path / "agy"
    base.mkdir()
    (base / "AGENTS.md").write_text("Plan before you code.", encoding="utf-8")

    cfg = _make_cfg("agy-mcp-server", base)
    cb = _make_context_builder(tmp_path, include_mcp_context=True, mcp_servers={"agy-mcp-server": cfg})

    prompt = cb.build_system_prompt()
    assert "## MCP Persistence Pointers" in prompt
    assert "Plan before you code." in prompt


def test_system_prompt_silently_skips_when_tools_config_absent(tmp_path: Path) -> None:
    """When tools_config is missing, no crash, no MCP block (back-compat)."""
    defaults = AgentDefaults(include_mcp_context=True)
    cb = ContextBuilder(tmp_path)
    cb.agents_config = SimpleNamespace(defaults=defaults)
    # Intentionally do NOT set cb.tools_config.

    prompt = cb.build_system_prompt()
    assert "## MCP Persistence Pointers" not in prompt


def test_system_prompt_silently_skips_when_agents_config_absent(tmp_path: Path) -> None:
    """When agents_config is missing, default to off (back-compat)."""
    cb = ContextBuilder(tmp_path)
    # Intentionally do NOT set cb.agents_config; tools_config has servers.
    base = tmp_path / "agy"
    base.mkdir()
    (base / "AGENTS.md").write_text("X", encoding="utf-8")
    cfg = _make_cfg("agy-mcp-server", base)
    cb.tools_config = SimpleNamespace(mcp_servers={"agy-mcp-server": cfg})

    prompt = cb.build_system_prompt()
    assert "## MCP Persistence Pointers" not in prompt
