"""Tests for the builtin ``mcp-router`` skill (Phase 1, FEMTOBOT_MCP_IMPROVEMENT_PLAN.md).

Verifies:
  - The skill is discovered by ``SkillsLoader`` from the bundled skills dir.
  - The frontmatter metadata is parsed (``always: false`` honored).
  - The skill body contains the decision matrix and safety contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from femtobot.agent.skills import BUILTIN_SKILLS_DIR, SkillsLoader

# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_mcp_router_skill_file_exists_on_disk() -> None:
    """The SKILL.md file is shipped inside the femtobot package."""
    skill_file = BUILTIN_SKILLS_DIR / "mcp-router" / "SKILL.md"
    assert skill_file.is_file(), (
        f"Expected builtin skill at {skill_file}; femtobot/skills/mcp-router/ not packaged"
    )


def test_mcp_router_skill_is_discovered(workspace_path: Path) -> None:
    """SkillsLoader picks up mcp-router from the builtin skills dir."""
    loader = SkillsLoader(workspace_path)
    skills = loader.list_skills(filter_unavailable=False)

    names = [entry["name"] for entry in skills]
    assert "mcp-router" in names, (
        f"mcp-router must be auto-discovered. Found: {names}"
    )

    entry = next(e for e in skills if e["name"] == "mcp-router")
    assert entry["source"] == "builtin"
    assert entry["path"].endswith("femtobot/skills/mcp-router/SKILL.md")


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------


def test_mcp_router_metadata_parsed(workspace_path: Path) -> None:
    """YAML frontmatter is parsed, and ``always: false`` is honored."""
    loader = SkillsLoader(workspace_path)
    raw_meta = loader.get_skill_metadata("mcp-router")
    assert isinstance(raw_meta, dict)

    # Top-level keys
    assert raw_meta.get("name") == "mcp-router"
    assert "description" in raw_meta

    # Nested femtobot metadata
    femtobot_meta = loader._parse_femtobot_metadata(raw_meta.get("metadata"))
    assert femtobot_meta.get("always") is False, (
        "mcp-router must default to always=false (opt-in, not always-loaded)"
    )


def test_mcp_router_is_not_always_loaded(workspace_path: Path) -> None:
    """``get_always_skills()`` excludes mcp-router because always=false."""
    loader = SkillsLoader(workspace_path)
    assert "mcp-router" not in loader.get_always_skills()


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------


def test_mcp_router_skill_content_has_decision_matrix(workspace_path: Path) -> None:
    """The skill body contains the routing decision matrix."""
    content = loader_load_skill_md(loader := SkillsLoader(workspace_path), "mcp-router")
    assert content is not None

    expected_phrases = [
        "When to delegate",
        "When NOT to delegate",
        "Server selection",
        "Required parameters",
        "Confirm gate",
        "agy_run_task",
        "claude_run_task",
        "mode=safe",
        "confirm=true",
        "workspace_path",
    ]
    missing = [p for p in expected_phrases if p not in content]
    assert not missing, f"SKILL.md is missing required phrases: {missing}"


def test_mcp_router_skill_warns_against_speculative_confirm(workspace_path: Path) -> None:
    """Safety contract: never set confirm=true without explicit approval."""
    content = loader_load_skill_md(loader := SkillsLoader(workspace_path), "mcp-router")
    assert content is not None
    assert "NEVER" in content
    assert "explicit" in content.lower()


def test_mcp_router_skill_load_skills_for_context_strips_frontmatter(
    workspace_path: Path,
) -> None:
    """``load_skills_for_context`` returns body without YAML frontmatter."""
    loader = SkillsLoader(workspace_path)
    body = loader.load_skills_for_context(["mcp-router"])
    assert body.startswith("### Skill: mcp-router")
    # Frontmatter must be stripped
    assert not body.lstrip().startswith("---")
    assert "When to delegate" in body


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def loader_load_skill_md(loader: SkillsLoader, name: str) -> str | None:
    """Thin wrapper that asserts the skill exists before returning its content."""
    content = loader.load_skill(name)
    if content is None:
        pytest.fail(f"Skill '{name}' not loadable from {loader.builtin_skills}")
    return content
