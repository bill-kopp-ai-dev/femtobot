"""Per-tool risk taxonomy for the v0.1.0-ui.0+ permission prompt layer.

This module is **new** in v0.1.0-ui.0 (plan T14, decision Q4+A, post-revision
F1 of the parity plan). The previous assumption was that
``security/command_guard.py`` already exposed a risk classification — it
does not (it only does path-safety / deny-pattern matching for shell
commands). The risk taxonomy is therefore defined here, against the
**real** tool names in :mod:`femtobot.agent.tools` (verified against
the registry on 2026-07-15):

  =======================  ==========================================
  Tool name (registry)     Source
  =======================  ==========================================
  ``exec``                 :class:`femtobot.agent.tools.shell.ExecTool`
  ``long_task``            :class:`femtobot.agent.tools.long_task.LongTaskTool`
  ``complete_goal``        :class:`femtobot.agent.tools.long_task.CompleteGoalTool`
  ``ask_orchestrator``     :class:`femtobot.agent.tools.ask_orchestrator.AskOrchestratorTool`
  ``web_fetch``            :class:`femtobot.agent.tools.web.WebFetchTool`
  ``web_search``           :class:`femtobot.agent.tools.web.WebSearchTool`
  ``read_file``            :class:`femtobot.agent.tools.filesystem.ReadFileTool`
  ``write_file``           :class:`femtobot.agent.tools.filesystem.WriteFileTool`
  ``edit_file``            :class:`femtobot.agent.tools.filesystem.EditFileTool`
  ``list_dir``             :class:`femtobot.agent.tools.filesystem.ListDirTool`
  ``find_files``           :class:`femtobot.agent.tools.search.FindFilesTool`
  ``grep``                 :class:`femtobot.agent.tools.search.GrepTool`
  ``apply_patch``          :class:`femtobot.agent.tools.apply_patch.ApplyPatchTool`
  ``femtobot_timer``       :class:`femtobot.agent.tools.time.FemtobotTimerTool`
  =======================  ==========================================

Risk levels
-----------

``high``    — requires explicit user confirmation (when the prompt is
              enabled and ``high_risk_only`` is true). These are tools
              that either run arbitrary subprocesses, dispatch a
              sub-agent, cross the workspace boundary, or post data
              to external URLs.

``medium``  — modifies state inside the workspace, or reads from the
              public internet (GET only). Passes silently in the
              default ``high_risk_only=true`` mode. Setting
              ``high_risk_only=false`` will surface them too.

``low``     — pure read / list / search operations. Always passes
              silently. The Q4 decision is that these are too noisy to
              ever prompt for.

The taxonomy is intentionally hard-coded (no config override yet) — the
list of "what is dangerous" is a project-level safety decision, not a
per-user preference. If a new tool is added in the future without
explicit classification, it defaults to ``"medium"`` (the conservative
mid-point: it could require prompting in the future but does not break
existing ``high_risk_only`` users).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class RiskLevel(str, Enum):
    """Tool-call risk level for the parity permission prompt layer."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ---------------------------------------------------------------------------
# v0.1.0-ui.0+ — taxonomy (Q4=A, expanded per Bill's "adicionar mais tools
# como high" feedback; see parity plan §11 Q4 and T14 for context).
# ---------------------------------------------------------------------------
# Every built-in tool is classified. Unknown tool names default to MEDIUM
# so a missed entry can never silently become "low".

_HIGH_RISK: frozenset[str] = frozenset(
    {
        # Arbitrary subprocess execution — the most dangerous surface.
        # This is the only tool that runs an OS command on the user's
        # behalf and is the canonical "ask first" target.
        "exec",
        # Sub-agent dispatch — hands control to a long-running goal.
        # Out-of-band from the user's current REPL turn.
        "long_task",
        # "I've finished" marker for a long_task; not destructive in
        # itself but only meaningful inside an active goal, and the
        # user has not necessarily asked for a goal to terminate.
        "complete_goal",
        # Cross-process ask to a supervisor / orchestrator — escapes
        # the local REPL.
        "ask_orchestrator",
    }
)

_MEDIUM_RISK: frozenset[str] = frozenset(
    {
        # In-workspace writes. ``apply_patch`` rejects paths outside
        # the workspace at the validator level (``apply_patch.py:43``),
        # so it is bounded; but it still mutates the user's project.
        "apply_patch",
        "write_file",
        "edit_file",
        # External GET — bounded by the SSRF guard + the workspace
        # loopback allowlist, but still touches the public internet.
        "web_fetch",
    }
)

_LOW_RISK: frozenset[str] = frozenset(
    {
        # Read-only file / directory / search operations.
        "read_file",
        "list_dir",
        "find_files",
        "grep",
        # Search engine wrapper — no mutation, no auth, public-only.
        "web_search",
        # Pure clock / timezone helper.
        "femtobot_timer",
    }
)


@dataclass(frozen=True)
class RiskAssessment:
    """The result of classifying one tool call.

    ``level``     — see :class:`RiskLevel`.
    ``reason``    — short human-readable explanation (used in the
                    permission prompt body and in the log line).
    ``in_scope``  — whether the workspace-boundary check would elevate
                    a MEDIUM tool to HIGH (e.g. ``write_file`` with a
                    path that resolves outside the workspace). ``None``
                    for HIGH / LOW tools, ``True`` / ``False`` for
                    MEDIUM tools depending on the path check.
    """

    level: RiskLevel
    reason: str
    in_scope: bool | None = None


def _workspace_in_scope(workspace_root: str | None, path: str) -> bool:
    """Return True if ``path`` resolves inside ``workspace_root``.

    Cheap implementation that does not require importing
    ``workspace_policy`` (which can have a heavier import cost); the
    real workspace-policy check is a superset of this and is what
    :func:`femtobot.security.workspace_policy.is_path_within` does.
    Mirrors that helper's behaviour: prefix-based, normalised, and
    treating ``~`` literally (the agent's tool layer is expected to
    expand ``~`` before calling us).
    """
    if not workspace_root or not path:
        return True
    try:
        from pathlib import Path

        root = Path(workspace_root).expanduser().resolve()
        target = Path(path).expanduser().resolve()
    except Exception:
        # Resolution failure — assume in-scope so the caller can apply
        # its own stricter check before deciding.
        return True
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def classify_tool(
    tool_name: str,
    params: dict | None = None,
    *,
    workspace_root: str | None = None,
) -> RiskAssessment:
    """Return the :class:`RiskAssessment` for a tool call.

    ``params`` is the parameter dict the agent is about to invoke the
    tool with. It is consulted to elevate certain MEDIUM tools to
    HIGH when the resolved path crosses the workspace boundary
    (``write_file`` / ``edit_file`` / ``apply_patch``).

    ``workspace_root`` is the active instance's expanded workspace
    directory. Pass ``None`` to skip the boundary check (the MEDIUM
    classification stays MEDIUM).
    """
    name = (tool_name or "").strip()
    params = params or {}

    if name in _HIGH_RISK:
        reasons = {
            "exec": "Runs a shell command on your machine.",
            "long_task": "Spawns a long-running sub-agent in the background.",
            "complete_goal": "Ends a long-running sub-agent goal.",
            "ask_orchestrator": "Sends a question to the orchestrator / supervisor.",
        }
        return RiskAssessment(level=RiskLevel.HIGH, reason=reasons.get(name, "High-risk tool."))

    if name in _MEDIUM_RISK:
        if name == "apply_patch":
            # ``apply_patch`` has no top-level ``path`` — its real shape is
            # ``{"edits": [{"path": ..., "action": ...}, ...]}`` (see
            # ``agent/tools/apply_patch.py:86-103``). Check every edit's
            # path; if ANY of them resolves outside the workspace, the
            # whole call is elevated to HIGH.
            edits = params.get("edits")
            paths = [
                str(e.get("path"))
                for e in edits
                if isinstance(e, dict) and e.get("path")
            ] if isinstance(edits, list) else []
            out_of_scope = [
                p for p in paths if _workspace_in_scope(workspace_root, p) is False
            ]
            if out_of_scope:
                return RiskAssessment(
                    level=RiskLevel.HIGH,
                    reason=(
                        f"apply_patch targets a path outside the active workspace "
                        f"({out_of_scope[0]!r})."
                    ),
                    in_scope=False,
                )
            return RiskAssessment(
                level=RiskLevel.MEDIUM,
                reason="apply_patch modifies a file inside the workspace.",
                in_scope=True if paths else None,
            )
        if name in {"write_file", "edit_file"}:
            target_path = str(params.get("path") or params.get("file_path") or params.get("target") or "")
            in_scope = _workspace_in_scope(workspace_root, target_path) if target_path else None
            if in_scope is False:
                return RiskAssessment(
                    level=RiskLevel.HIGH,
                    reason=(
                        f"{name} targets a path outside the active workspace "
                        f"({target_path!r})."
                    ),
                    in_scope=False,
                )
            return RiskAssessment(
                level=RiskLevel.MEDIUM,
                reason=f"{name} modifies a file inside the workspace.",
                in_scope=True if in_scope is not None else None,
            )
        if name == "web_fetch":
            return RiskAssessment(
                level=RiskLevel.MEDIUM,
                reason="Fetches a URL from the public internet (GET).",
            )
        return RiskAssessment(level=RiskLevel.MEDIUM, reason=f"{name} is a medium-risk tool.")

    if name in _LOW_RISK:
        return RiskAssessment(level=RiskLevel.LOW, reason=f"{name} is read-only.")

    # Unknown tool — conservative default. The Q4 decision is that a
    # missed classification must never silently downgrade to LOW (that
    # would let a new tool bypass the prompt). MEDIUM is the safe
    # mid-point: it does not break existing ``high_risk_only`` users.
    return RiskAssessment(
        level=RiskLevel.MEDIUM,
        reason=f"{name!r} is unclassified; treating as medium-risk by default.",
    )


def should_prompt(
    assessment: RiskAssessment,
    *,
    enabled: bool,
    high_risk_only: bool,
) -> bool:
    """Apply the user's permission-prompt knobs to an assessment.

    Returns ``True`` iff the user should be prompted before the tool runs.

      * ``enabled=False``  → never prompt (legacy Femtobot).
      * ``enabled=True``, ``high_risk_only=True``  → prompt only HIGH.
      * ``enabled=True``, ``high_risk_only=False`` → prompt HIGH + MEDIUM.
    """
    if not enabled:
        return False
    if high_risk_only:
        return assessment.level == RiskLevel.HIGH
    return assessment.level in (RiskLevel.HIGH, RiskLevel.MEDIUM)


def all_known_tools() -> tuple[str, ...]:
    """Return the union of classified tool names (handy for tests/docs)."""
    return tuple(sorted(_HIGH_RISK | _MEDIUM_RISK | _LOW_RISK))


def tools_by_level() -> dict[RiskLevel, tuple[str, ...]]:
    """Return a mapping ``level → sorted tool names`` (handy for docs)."""
    return {
        RiskLevel.HIGH: tuple(sorted(_HIGH_RISK)),
        RiskLevel.MEDIUM: tuple(sorted(_MEDIUM_RISK)),
        RiskLevel.LOW: tuple(sorted(_LOW_RISK)),
    }


def iter_risky_tools() -> Iterable[tuple[str, RiskLevel]]:
    """Iterate ``(tool_name, level)`` over all classified tools."""
    for n in sorted(_HIGH_RISK):
        yield n, RiskLevel.HIGH
    for n in sorted(_MEDIUM_RISK):
        yield n, RiskLevel.MEDIUM
    for n in sorted(_LOW_RISK):
        yield n, RiskLevel.LOW
