"""Tests for the AGENTS.md template MCP-Aware Operating Rules section.

Refs: FEMTOBOT_MCP_IMPROVEMENT_PLAN.md Fase 4.
"""

from __future__ import annotations

from pathlib import Path

TEMPLATE_PATH = Path(
    "/home/bill/Codes/agents/femtobot/femtobot/templates/AGENTS.md"
)


# ---------------------------------------------------------------------------
# Template shape
# ---------------------------------------------------------------------------


def test_template_file_exists() -> None:
    """The bundled AGENTS.md template is shipped at the expected path."""
    assert TEMPLATE_PATH.is_file(), f"AGENTS.md template not found at {TEMPLATE_PATH}"


def test_template_has_mcp_section() -> None:
    """The template contains the 'MCP-Aware Operating Rules' section."""
    content = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "## MCP-Aware Operating Rules" in content


def test_template_mcp_section_contains_expected_rules() -> None:
    """The section enumerates the five operating rules from the plan."""
    content = TEMPLATE_PATH.read_text(encoding="utf-8")
    section = content.split("## MCP-Aware Operating Rules", 1)[1].split(
        "## See Also", 1
    )[0]

    # Five rules (one per bullet).
    rules = [
        "Default to local tools",
        "*_run_task",
        "mode=safe",
        "Persistence is per-server",
        "MCP tools are long-running",
    ]
    for rule in rules:
        assert rule in section, f"AGENTS.md MCP section missing rule: {rule!r}"


def test_template_mcp_section_does_not_overwrite_existing_agents() -> None:
    """The template preserves existing sections (sync is non-destructive).

    This is a static check on the bundled template: a sync implementation
    must read this file, parse it, and only emit the missing pieces into a
    fresh workspace AGENTS.md. Existing AGENTS.md files are never
    overwritten.
    """
    content = TEMPLATE_PATH.read_text(encoding="utf-8")
    # Existing sections that must remain.
    assert "## Identity" in content
    assert "## Memory Layout" in content
    assert "## Operating Principles" in content
    assert "## Multi-Instance Notes" in content
    # New section.
    assert "## MCP-Aware Operating Rules" in content
    # See Also updated.
    assert "docs/mcp.md" in content


def test_template_mcp_section_warns_against_speculative_confirm() -> None:
    """Safety contract: the confirm gate is described in the section."""
    content = TEMPLATE_PATH.read_text(encoding="utf-8")
    section = content.split("## MCP-Aware Operating Rules", 1)[1].split(
        "## See Also", 1
    )[0]
    assert "Never set it speculatively" in section or "never set it speculatively" in section
    assert "confirm=true" in section
    assert "confirm=true" in section


# ---------------------------------------------------------------------------
# sync_workspace_templates smoke
# ---------------------------------------------------------------------------


def test_sync_workspace_templates_does_not_overwrite_existing_agents(tmp_path: Path) -> None:
    """``sync_workspace_templates`` must not overwrite a user's existing AGENTS.md.

    This is a regression guard: the bundled template may grow, but an
    existing AGENTS.md in the workspace stays put.
    """
    from femtobot.utils.helpers import sync_workspace_templates

    ws = tmp_path / "workspace"
    ws.mkdir()
    user_agents = ws / "AGENTS.md"
    sentinel = "# user-customized AGENTS.md\n\ndo not touch me\n"
    user_agents.write_text(sentinel, encoding="utf-8")

    sync_workspace_templates(ws, silent=True)

    assert user_agents.read_text(encoding="utf-8") == sentinel, (
        "sync_workspace_templates overwrote existing AGENTS.md"
    )


def test_sync_workspace_templates_creates_agents_when_missing(tmp_path: Path) -> None:
    """When AGENTS.md is absent, sync creates it from the bundled template."""
    from femtobot.utils.helpers import sync_workspace_templates

    ws = tmp_path / "workspace"
    ws.mkdir()

    sync_workspace_templates(ws, silent=True)

    created = ws / "AGENTS.md"
    assert created.exists(), f"AGENTS.md not created at {created}"
    body = created.read_text(encoding="utf-8")
    assert "## MCP-Aware Operating Rules" in body


# R2-femtobot (refactor-parity-with-nanobot.md Phase 3): the sync helper
# used to copy every ``templates/agent/*.md`` into the user workspace
# (identity.md, dream.md, tool_contract.md, evaluator.md, etc.).  Those
# files are internal prompt templates read in-memory by
# ``prompt_templates.render_template`` and must never be materialised on
# disk.  This guard freezes the contract: a fresh workspace contains
# exactly the canonical files, not the internal ones.
_LEAKED_TEMPLATES = {
    "identity.md",
    "tool_contract.md",
    "dream.md",
    "evaluator.md",
    "consolidator_archive.md",
    "subagent_system.md",
    "subagent_announce.md",
    "skills_section.md",
    "platform_policy.md",
    "max_iterations_message.md",
}


def test_sync_workspace_does_not_leak_internal_templates(tmp_path: Path) -> None:
    """A fresh workspace must not contain internal prompt templates."""
    from femtobot.utils.helpers import sync_workspace_templates

    ws = tmp_path / "workspace"

    sync_workspace_templates(ws, silent=True)

    leaked = {p.name for p in ws.iterdir() if p.is_file()} & _LEAKED_TEMPLATES
    assert not leaked, (
        f"sync_workspace_templates leaked internal templates into the workspace: "
        f"{leaked}"
    )


def test_sync_workspace_creates_only_canonical_files(tmp_path: Path) -> None:
    """A fresh workspace contains exactly the canonical user-facing files."""
    from femtobot.utils.helpers import sync_workspace_templates

    ws = tmp_path / "workspace"

    sync_workspace_templates(ws, silent=True)

    expected_files = {"AGENTS.md", "SOUL.md", "USER.md", "goal_runtime.md"}
    expected_dirs = {"memory", "skills"}

    actual = {p.name for p in ws.iterdir() if not p.name.startswith(".")}
    actual_files = {n for n in actual if (ws / n).is_file()}
    actual_dirs = {n for n in actual if (ws / n).is_dir()}

    assert actual_files == expected_files, (
        f"workspace files mismatch: got {actual_files}, expected {expected_files}"
    )
    assert actual_dirs == expected_dirs, (
        f"workspace dirs mismatch: got {actual_dirs}, expected {expected_dirs}"
    )
