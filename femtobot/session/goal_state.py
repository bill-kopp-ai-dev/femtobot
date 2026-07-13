"""Session metadata helpers for sustained goals (e.g. ``long_task`` / ``complete_goal``).

Tools set ``metadata[GOAL_STATE_KEY]``. Reads accept the legacy session key ``thread_goal``
for older sessions. Callers use ``goal_state_runtime_lines``, ``goal_state_ws_blob``, and
``runner_wall_llm_timeout_s`` without importing tool implementations.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Mapping, MutableMapping

from femtobot.session.manager import SessionManager

GOAL_STATE_KEY = "goal_state"
# Older builds stored the same JSON blob under this key.
_LEGACY_GOAL_STATE_SESSION_KEY = "thread_goal"
MAX_GOAL_OBJECTIVE_CHARS = 4000
_MAX_OBJECTIVE_WS = 600

GOAL_STATUS_ACTIVE = "active"
GOAL_STATUS_COMPLETED = "completed"
GOAL_STATUS_CANCELLED = "cancelled"
GOAL_STATUS_BLOCKED = "blocked"

GOAL_ACTIONS = ("complete", "cancel", "block", "replace")
GOAL_FINAL_ACTIONS = ("complete", "cancel", "block")

_GOAL_REQUESTED_KEY = "goal_requested"
_GOAL_REQUESTED_IMPLICITLY_KEY = "goal_requested_implicitly"
_GOAL_STARTED_AT_KEY = "goal_started_at"
_GOAL_REPLACED_AT_KEY = "goal_replaced_at"
_GOAL_BLOCK_REASON_KEY = "goal_block_reason"
_GOAL_WAITING_ON_KEY = "goal_waiting_on"
_GOAL_GOAL_ID_KEY = "goal_id"

# M1 of long-task-by-default: opened-questions heuristic for "self-containment".
# A goal is considered non-self-contained when it ends with '?' or contains
# a question marker mid-sentence.  Conservative on purpose — false positives
# (rejecting a legitimate goal) hurt less than launching a runaway worker.
_OPEN_QUESTION_RE = re.compile(
    r"\?|^\s*(?:what|why|how|when|where|which|who|quem|como|onde|quando|"
    r"por que|porque|qual|quais|o que)\b",
    re.IGNORECASE,
)


def _session_goal_raw(metadata: Mapping[str, Any] | None) -> Any:
    if not metadata:
        return None
    if GOAL_STATE_KEY in metadata:
        return metadata.get(GOAL_STATE_KEY)
    return metadata.get(_LEGACY_GOAL_STATE_SESSION_KEY)


def discard_legacy_goal_state_key(metadata: MutableMapping[str, Any]) -> None:
    """Remove legacy metadata key after migrating writes to :data:`GOAL_STATE_KEY`."""
    metadata.pop(_LEGACY_GOAL_STATE_SESSION_KEY, None)


def goal_state_raw(metadata: Mapping[str, Any] | None) -> Any:
    """Return the session goal blob under :data:`GOAL_STATE_KEY` or the legacy key."""
    return _session_goal_raw(metadata)


def sustained_goal_active(metadata: Mapping[str, Any] | None) -> bool:
    """True when this session has an active sustained objective (``long_task`` bookkeeping)."""
    goal = parse_goal_state(goal_state_raw(metadata))
    return isinstance(goal, dict) and goal.get("status") == "active"


def sustained_goal_turn(
    metadata: Mapping[str, Any] | None,
    *,
    message_metadata: Mapping[str, Any] | None = None,
) -> bool:
    """True when this turn should use sustained-goal runtime limits."""
    if sustained_goal_active(metadata):
        return True
    if not message_metadata:
        return False
    return str(message_metadata.get("original_command") or "").strip() == "/goal"


def parse_goal_state(blob: Any) -> dict[str, Any] | None:
    if blob is None:
        return None
    if isinstance(blob, dict):
        return blob
    if isinstance(blob, str):
        try:
            parsed = json.loads(blob)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def goal_state_runtime_lines(metadata: Mapping[str, Any] | None) -> list[str]:
    """Lines appended inside the Runtime Context block when a goal is active."""
    if not metadata:
        return []
    goal = parse_goal_state(_session_goal_raw(metadata))
    if not isinstance(goal, dict) or goal.get("status") != "active":
        return []
    objective = str(goal.get("objective") or "").strip()
    if not objective:
        return ["Goal: active (no objective text stored)."]
    if len(objective) > MAX_GOAL_OBJECTIVE_CHARS:
        objective = objective[:MAX_GOAL_OBJECTIVE_CHARS].rstrip() + "\n… (truncated)"
    out = ["Goal (active):", objective]
    hint = str(goal.get("ui_summary") or "").strip()
    if hint:
        out.append(f"Summary: {hint}")
    return out


def goal_state_ws_blob(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """JSON-safe snapshot for WebSocket ``goal_state`` events (one chat_id per frame)."""
    goal = parse_goal_state(_session_goal_raw(metadata)) if metadata else None
    if isinstance(goal, dict) and goal.get("status") == "active":
        objective = str(goal.get("objective") or "").strip()
        if len(objective) > _MAX_OBJECTIVE_WS:
            objective = objective[:_MAX_OBJECTIVE_WS].rstrip() + "…"
        summary = str(goal.get("ui_summary") or "").strip()[:120]
        blob: dict[str, Any] = {"active": True}
        if summary:
            blob["ui_summary"] = summary
        if objective:
            blob["objective"] = objective
        return blob
    return {"active": False}


def runner_wall_llm_timeout_s(
    sessions: SessionManager,
    session_key: str | None,
    *,
    metadata: Mapping[str, Any] | None = None,
    message_metadata: Mapping[str, Any] | None = None,
) -> float | None:
    """Wall-clock cap for :class:`~femtobot.agent.runner.AgentRunner` when streaming an LLM.

    Returns ``0.0`` to disable ``asyncio.wait_for`` around the request when this is a
    sustained-goal turn; ``None`` means use ``FEMTOBOT_LLM_TIMEOUT_S``. Pass in-memory
    ``metadata`` when the caller already holds :attr:`~femtobot.session.manager.Session.metadata`
    for this turn.
    """
    meta: Mapping[str, Any] | None = metadata
    if meta is None and session_key:
        meta = sessions.get_or_create(session_key).metadata
    return 0.0 if sustained_goal_turn(meta, message_metadata=message_metadata) else None


# ---------------------------------------------------------------------------
# M1 of long-task-by-default — explicit/implicit goal-requested predicates
# ---------------------------------------------------------------------------


def _msg_meta(message_metadata: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return message_metadata or {}


def explicit_goal_requested(message_metadata: Mapping[str, Any] | None) -> bool:
    """True when this turn was triggered by an explicit ``/goal <objective>`` slash command.

    The check is anchored on ``original_command == "/goal"`` — ``goal_requested``
    by itself is ambiguous because the long-task-by-default auto-wrap hook also
    sets it on every inbound.
    """
    meta = _msg_meta(message_metadata)
    return str(meta.get("original_command") or "").strip() == "/goal"


def implicit_goal_requested(message_metadata: Mapping[str, Any] | None) -> bool:
    """True when this turn is the bootstrap for a goal triggered implicitly.

    Set by the loop when ``by_default=True`` and the inbound is not a slash command;
    marks that the runner should call ``long_task`` *itself* to register the goal.
    The marker is the *implicit* variant — explicit ``/goal`` is handled by
    :func:`explicit_goal_requested`.
    """
    meta = _msg_meta(message_metadata)
    return meta.get(_GOAL_REQUESTED_IMPLICITLY_KEY) is True


def goal_bootstrap_requested(message_metadata: Mapping[str, Any] | None) -> bool:
    """True when the runner itself should bootstrap a goal at turn start.

    Distinguishes from ``explicit_goal_requested`` (slash command already
    wrote the blob) and from the legacy ``sustained_goal_turn`` (read-only
    check).  This is the predicate that gates ``LongTaskTool`` invocation
    inside the auto-wrap path.
    """
    return implicit_goal_requested(message_metadata) or explicit_goal_requested(message_metadata)


def goal_started_at(metadata: Mapping[str, Any] | None) -> float | None:
    """Wall-clock seconds (UTC) when the active goal was started.

    Stored in ``metadata[goal_started_at]`` by the bootstrap hook.  ``None``
    when the session has no recorded start time (e.g. legacy blob).
    """
    if not metadata:
        return None
    raw = metadata.get(_GOAL_STARTED_AT_KEY)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def goal_elapsed_s(metadata: Mapping[str, Any] | None, *, now: float | None = None) -> float:
    """Seconds since the active goal started; 0 if not measurable."""
    started = goal_started_at(metadata)
    if started is None:
        return 0.0
    current = float(now) if now is not None else time.time()
    return max(0.0, current - started)


def goal_block_reason(metadata: Mapping[str, Any] | None) -> str | None:
    """Optional human-readable reason captured when a goal is blocked."""
    if not metadata:
        return None
    raw = metadata.get(_GOAL_BLOCK_REASON_KEY)
    if raw is None:
        return None
    # Reject non-string payloads — defensive so we never surface
    # ``"b'foo'"`` from a stray ``bytes`` value in metadata.
    if not isinstance(raw, str):
        return None
    return raw.strip() or None


def goal_waiting_on(metadata: Mapping[str, Any] | None) -> str | None:
    """Tag identifying what the goal is currently waiting on, if any.

    Currently the only well-known value is ``"ask_orchestrator"``.
    """
    if not metadata:
        return None
    raw = metadata.get(_GOAL_WAITING_ON_KEY)
    if raw is None:
        return None
    if not isinstance(raw, str):
        return None
    return raw.strip() or None


def goal_id(metadata: Mapping[str, Any] | None) -> str | None:
    """Opaque id assigned to the active goal, when present."""
    if not metadata:
        return None
    raw = metadata.get(_GOAL_GOAL_ID_KEY)
    return str(raw) if raw is not None else None


def is_self_contained_objective(objective: str, *, allow_questions: bool = False) -> bool:
    """Heuristic — True when *objective* looks bounded and actionable.

    Used to validate ``LongTaskTool`` input when
    ``require_objective_self_containment=True``.  The check is intentionally
    conservative: a refusal is cheaper than a runaway worker.
    """
    text = (objective or "").strip()
    if not text:
        return False
    if allow_questions:
        return True
    return not bool(_OPEN_QUESTION_RE.search(text))


def normalize_goal_status(value: Any) -> str | None:
    """Map any acceptable spelling to the canonical lowercase status string."""
    if value is None:
        return None
    if isinstance(value, str):
        norm = value.strip().lower()
    else:
        return None
    if norm in {
        GOAL_STATUS_ACTIVE,
        GOAL_STATUS_COMPLETED,
        GOAL_STATUS_CANCELLED,
        GOAL_STATUS_BLOCKED,
    }:
        return norm
    return None


def reset_goal_continuation_marker(metadata: MutableMapping[str, Any]) -> None:
    """Clear any pending ``goal_continue``/``ask_wait`` markers on the session."""
    metadata.pop("goal_continue_rounds", None)
    metadata.pop("goal_pending_ask_correlation_id", None)


def mark_goal_waiting(
    metadata: MutableMapping[str, Any],
    *,
    waiting_on: str,
    correlation_id: str | None = None,
) -> None:
    """Persist the 'waiting' state so a restart can recover it."""
    metadata[_GOAL_WAITING_ON_KEY] = waiting_on
    if correlation_id:
        metadata["goal_pending_ask_correlation_id"] = correlation_id


def clear_goal_waiting(metadata: MutableMapping[str, Any]) -> None:
    """Inverse of :func:`mark_goal_waiting`."""
    metadata.pop(_GOAL_WAITING_ON_KEY, None)
    metadata.pop("goal_pending_ask_correlation_id", None)
