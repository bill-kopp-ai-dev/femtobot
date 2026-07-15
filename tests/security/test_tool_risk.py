"""Tests for the per-tool risk taxonomy (T14, post-Q4 expansion).

Covers:

  * High-risk tools (exec, long_task, complete_goal, ask_orchestrator)
    are correctly classified.
  * Medium-risk tools (write_file, edit_file, apply_patch, web_fetch)
    default to MEDIUM but are elevated to HIGH when the path resolves
    outside the workspace.
  * Low-risk tools (read_file, list_dir, find_files, grep, web_search,
    femtobot_timer) are read-only / safe.
  * Unknown tools default to MEDIUM (never silently LOW).
  * ``should_prompt`` honours the ``enabled`` and ``high_risk_only``
    knobs per the Q4 plan.
"""

from __future__ import annotations

import pytest

from femtobot.security.tool_risk import (
    RiskAssessment,
    RiskLevel,
    all_known_tools,
    classify_tool,
    iter_risky_tools,
    should_prompt,
    tools_by_level,
)


# ---------------------------------------------------------------------------
# High-risk tools (Q4=A, expanded per Bill)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["exec", "long_task", "complete_goal", "ask_orchestrator"],
)
def test_high_risk_tools(name: str) -> None:
    a = classify_tool(name)
    assert a.level == RiskLevel.HIGH
    assert a.reason  # non-empty reason


def test_exec_classification_carries_helpful_reason() -> None:
    a = classify_tool("exec")
    assert "shell" in a.reason.lower() or "command" in a.reason.lower()


# ---------------------------------------------------------------------------
# Medium-risk tools
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["write_file", "edit_file"])
def test_medium_risk_tools_in_scope(tmp_path, name: str) -> None:
    a = classify_tool(name, {"path": str(tmp_path / "ok.py")}, workspace_root=str(tmp_path))
    assert a.level == RiskLevel.MEDIUM
    assert a.in_scope is True


def test_apply_patch_in_scope(tmp_path) -> None:
    # apply_patch's real shape is a list of edits, each with its own
    # ``path`` (agent/tools/apply_patch.py:86-103) — no top-level ``path``.
    a = classify_tool(
        "apply_patch",
        {"edits": [{"path": str(tmp_path / "ok.py"), "action": "replace"}]},
        workspace_root=str(tmp_path),
    )
    assert a.level == RiskLevel.MEDIUM
    assert a.in_scope is True


def test_web_fetch_is_medium(tmp_path) -> None:
    a = classify_tool("web_fetch", {"url": "https://example.com"}, workspace_root=str(tmp_path))
    assert a.level == RiskLevel.MEDIUM
    assert a.in_scope is None  # web_fetch is not a path-based tool


def test_write_file_outside_workspace_is_promoted_to_high(tmp_path) -> None:
    outside = tmp_path.parent / "evil.py"
    a = classify_tool(
        "write_file",
        {"path": str(outside)},
        workspace_root=str(tmp_path),
    )
    assert a.level == RiskLevel.HIGH
    assert a.in_scope is False
    assert "outside" in a.reason.lower()


def test_edit_file_outside_workspace_is_promoted_to_high(tmp_path) -> None:
    outside = tmp_path.parent / "evil.py"
    a = classify_tool(
        "edit_file",
        {"path": str(outside), "target": str(outside)},
        workspace_root=str(tmp_path),
    )
    assert a.level == RiskLevel.HIGH


def test_apply_patch_outside_workspace_is_promoted_to_high(tmp_path) -> None:
    outside = tmp_path.parent / "evil.py"
    a = classify_tool(
        "apply_patch",
        {"edits": [{"path": str(outside), "action": "replace"}]},
        workspace_root=str(tmp_path),
    )
    assert a.level == RiskLevel.HIGH
    assert a.in_scope is False


def test_apply_patch_with_one_edit_outside_workspace_is_promoted_to_high(tmp_path) -> None:
    """A multi-edit apply_patch call is HIGH if ANY edit crosses the boundary,
    even when the others stay inside the workspace."""
    outside = tmp_path.parent / "evil.py"
    inside = tmp_path / "ok.py"
    a = classify_tool(
        "apply_patch",
        {
            "edits": [
                {"path": str(inside), "action": "replace"},
                {"path": str(outside), "action": "replace"},
            ]
        },
        workspace_root=str(tmp_path),
    )
    assert a.level == RiskLevel.HIGH
    assert a.in_scope is False


def test_web_fetch_is_medium_even_with_no_workspace() -> None:
    """web_fetch never uses the workspace boundary check — it's an
    outbound HTTP GET, the safety guard is the SSRF block."""
    a = classify_tool("web_fetch", {"url": "https://example.com"})
    assert a.level == RiskLevel.MEDIUM
    assert a.in_scope is None


# ---------------------------------------------------------------------------
# Low-risk tools
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["read_file", "list_dir", "find_files", "grep", "web_search", "femtobot_timer"],
)
def test_low_risk_tools(name: str) -> None:
    a = classify_tool(name)
    assert a.level == RiskLevel.LOW
    assert a.in_scope is None


# ---------------------------------------------------------------------------
# Unknown tools (conservative default)
# ---------------------------------------------------------------------------


def test_unknown_tool_defaults_to_medium() -> None:
    a = classify_tool("mcp_server_42_exploit")
    assert a.level == RiskLevel.MEDIUM
    assert "unclassified" in a.reason.lower()


def test_empty_tool_name_defaults_to_medium() -> None:
    a = classify_tool("")
    assert a.level == RiskLevel.MEDIUM


def test_whitespace_tool_name_defaults_to_medium() -> None:
    a = classify_tool("   ")
    assert a.level == RiskLevel.MEDIUM


# ---------------------------------------------------------------------------
# should_prompt() — config knob matrix (Q4)
# ---------------------------------------------------------------------------


def test_should_prompt_disabled_never_prompts() -> None:
    a = classify_tool("exec")
    assert should_prompt(a, enabled=False, high_risk_only=True) is False
    assert should_prompt(a, enabled=False, high_risk_only=False) is False


def test_should_prompt_high_risk_only_filters_medium() -> None:
    """Q4 — default behaviour. Only HIGH triggers a prompt."""
    high = classify_tool("exec")
    med = classify_tool("read_file")  # this is actually LOW; use a real MEDIUM
    med = classify_tool("web_fetch", {"url": "https://example.com"})
    low = classify_tool("read_file")

    assert should_prompt(high, enabled=True, high_risk_only=True) is True
    assert should_prompt(med, enabled=True, high_risk_only=True) is False
    assert should_prompt(low, enabled=True, high_risk_only=True) is False


def test_should_prompt_high_risk_only_false_includes_medium() -> None:
    high = classify_tool("exec")
    med = classify_tool("web_fetch", {"url": "https://example.com"})
    low = classify_tool("read_file")

    assert should_prompt(high, enabled=True, high_risk_only=False) is True
    assert should_prompt(med, enabled=True, high_risk_only=False) is True
    assert should_prompt(low, enabled=True, high_risk_only=False) is False


# ---------------------------------------------------------------------------
# Introspection helpers
# ---------------------------------------------------------------------------


def test_all_known_tools_includes_every_classified_tool() -> None:
    tools = set(all_known_tools())
    expected = {"exec", "long_task", "complete_goal", "ask_orchestrator",
                "apply_patch", "write_file", "edit_file", "web_fetch",
                "read_file", "list_dir", "find_files", "grep",
                "web_search", "femtobot_timer"}
    assert tools == expected


def test_tools_by_level_partitions_correctly() -> None:
    by_level = tools_by_level()
    assert set(by_level[RiskLevel.HIGH]) == {
        "exec", "long_task", "complete_goal", "ask_orchestrator",
    }
    assert set(by_level[RiskLevel.MEDIUM]) == {
        "apply_patch", "write_file", "edit_file", "web_fetch",
    }
    assert set(by_level[RiskLevel.LOW]) == {
        "read_file", "list_dir", "find_files", "grep",
        "web_search", "femtobot_timer",
    }


def test_iter_risky_tools_yields_every_tool_once() -> None:
    seen = {name for name, _ in iter_risky_tools()}
    assert seen == set(all_known_tools())


# ---------------------------------------------------------------------------
# Dataclass sanity
# ---------------------------------------------------------------------------


def test_risk_assessment_is_frozen() -> None:
    a = RiskAssessment(level=RiskLevel.LOW, reason="x")
    with pytest.raises((AttributeError, TypeError)):
        a.level = RiskLevel.HIGH  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Regression: do NOT silently pass an ``exec`` outside the workspace
# (it is HIGH by category — no boundary check is even needed).
# ---------------------------------------------------------------------------


def test_exec_outside_workspace_still_high() -> None:
    a = classify_tool("exec", {"command": "rm -rf /tmp/foo"}, workspace_root=None)
    assert a.level == RiskLevel.HIGH
