"""Long-task (sustained goal) tools.

This module implements the two tools that mediate goal state from the
LLM's side:

* :class:`LongTaskTool` (``long_task``) — bootstrap or replace the active
  sustained goal for this session.
* :class:`CompleteGoalTool` (``complete_goal``) — terminate the active
  goal with ``complete`` / ``cancel`` / ``block`` / ``replace`` actions.

Both tools reuse the slash-command domain logic so the agent and the
human end up with the same code path.  When the configuration flag
``by_default=true`` is set, the loop auto-wraps incoming messages as
goals; otherwise the agent must explicitly call :class:`LongTaskTool`.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from femtobot.agent.goal_permission import (
    GoalMutationNotAllowedError,
    goal_mutation_allowed,
    require_goal_mutation_permission,
    revoke_goal_mutation_permission,
)
from femtobot.agent.tools.base import Tool, tool_parameters
from femtobot.agent.tools.context import ContextAware, RequestContext, ToolContext
from femtobot.agent.tools.schema import StringSchema, tool_parameters_schema
from femtobot.bus.goal_events import publish_goal_state_changed
from femtobot.session.goal_state import (
    GOAL_STATE_KEY,
    GOAL_ACTIONS,
    GOAL_FINAL_ACTIONS,
    MAX_GOAL_OBJECTIVE_CHARS,
    clear_goal_waiting,
    discard_legacy_goal_state_key,
    is_self_contained_objective,
    normalize_goal_status,
    parse_goal_state,
    reset_goal_continuation_marker,
    sustained_goal_active,
)


def _now_epoch() -> float:
    """Wall-clock seconds since epoch (UTC).

    Used for ``goal_started_at`` which feeds ``goal_elapsed_s()`` and
    runtime-context elapsed-time math.
    """
    return time.time()


def _now_iso_ms() -> str:
    """ISO-8601 UTC timestamp with millisecond precision.

    Used for blob ``created_at``/``updated_at``/``replaced_at`` so the
    status output and event streams show real dates rather than raw
    epoch floats.
    """
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _persist_session(ctx: ToolContext, session: Any) -> None:
    """Best-effort ``sessions.save`` for tool-driven goal mutations.

    Tools can't reliably await the next turn — without this save, a
    crash between the tool call and the loop's next save would lose
    the goal-state mutation.  Errors are swallowed because the regular
    loop save path will catch up on the next turn.
    """
    sessions = getattr(ctx, "sessions", None)
    if sessions is None or session is None:
        return
    try:
        sessions.save(session)
    except Exception:
        # Persistence is best-effort; tools must never raise from
        # their save path because that would mask the tool's result.
        pass


_MAX_UI_SUMMARY = 120


def _clean_ui_summary(value: str | None) -> str | None:
    """Trim and cap ``ui_summary`` to ``_MAX_UI_SUMMARY`` chars."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:_MAX_UI_SUMMARY]


# ---------------------------------------------------------------------------
# Helpers shared by both tools
# ---------------------------------------------------------------------------


def _resolve_session(ctx: ToolContext, channel: str, chat_id: str) -> Any:
    """Return the session bound to ``channel:chat_id`` for this tool."""
    sessions = getattr(ctx, "sessions", None)
    if sessions is None:
        return None
    key = f"{channel}:{chat_id}"
    return sessions.get_or_create(key)


def _publish(
    ctx: ToolContext,
    *,
    channel: str,
    chat_id: str,
    session_key: str | None,
    metadata: dict[str, Any],
) -> None:
    publish_goal_state_changed(
        session_key=session_key,
        channel=channel,
        chat_id=chat_id,
        session_metadata=metadata,
        bus=getattr(ctx, "runtime_events", None),
    )


def _validate_objective(objective: Any) -> tuple[str | None, str | None]:
    """Return ``(clean_objective, error_message)`` for ``LongTaskTool`` input."""
    if not isinstance(objective, str):
        return None, "Error: 'objective' must be a string."
    text = objective.strip()
    if not text:
        return None, "Error: 'objective' is required and cannot be empty."
    if len(text) > MAX_GOAL_OBJECTIVE_CHARS:
        return None, (
            f"Error: 'objective' exceeds {MAX_GOAL_OBJECTIVE_CHARS} characters; "
            "tighten the wording and try again."
        )
    return text, None


def _self_containment_required(ctx: ToolContext | None) -> bool:
    """Mirror ``LongTaskConfig.require_objective_self_containment`` for tests."""
    if ctx is None:
        return True
    cfg = getattr(ctx, "long_task_config", None)
    if cfg is None:
        return True
    return bool(getattr(cfg, "require_objective_self_containment", True))


# ---------------------------------------------------------------------------
# LongTaskTool
# ---------------------------------------------------------------------------


@tool_parameters(
    tool_parameters_schema(
        objective=StringSchema(
            "Concrete, self-contained, verifiable objective for this session. "
            "Avoid open-ended questions — frame the work as a bounded task.",
            min_length=1,
            max_length=MAX_GOAL_OBJECTIVE_CHARS,
        ),
        ui_summary=StringSchema(
            "Optional short label shown in status output (max 120 chars).",
            max_length=120,
            nullable=True,
        ),
        required=["objective"],
    )
)
class LongTaskTool(Tool, ContextAware):
    """Bootstrap or replace the active sustained goal for this session."""

    name = "long_task"
    description = (
        "Record a durable sustained goal for this session. After this call, "
        "the agent continues working toward the objective until it explicitly "
        "calls `complete_goal` or hits a guardrail. Use this once per session "
        "when the work is multi-step, requires ongoing context, or could "
        "benefit from progress tracking. Do not use for one-shot replies."
    )

    def __init__(self) -> None:
        self._channel = ""
        self._chat_id = ""
        self._tool_ctx: ToolContext | None = None

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        tool = cls()
        tool._tool_ctx = ctx
        return tool

    def set_context(self, ctx: RequestContext) -> None:
        self._channel = ctx.channel
        self._chat_id = ctx.chat_id

    def has_capability(self, capability: str) -> bool:
        return capability in {"goal-management", "long-running"}

    def get_capabilities(self) -> list[str]:
        return ["goal-management", "long-running"]

    async def execute(self, objective: str, ui_summary: str | None = None) -> str:
        text, err = _validate_objective(objective)
        if err:
            return err
        if self._tool_ctx is None:
            return "Error: tool context not bound; cannot create goal."
        if _self_containment_required(self._tool_ctx) and not is_self_contained_objective(text):
            return (
                "Error: 'objective' looks like an open-ended question. "
                "Reframe it as a concrete, bounded task before retrying."
            )

        try:
            require_goal_mutation_permission()
        except GoalMutationNotAllowedError as exc:
            return str(exc)

        session = _resolve_session(self._tool_ctx, self._channel, self._chat_id)
        if session is None:
            return "Error: no active session — cannot create a goal."

        epoch_now = _now_epoch()
        iso_now = _now_iso_ms()
        md = dict(session.metadata or {})
        existing = parse_goal_state(md.get(GOAL_STATE_KEY))
        blob = {
            "status": normalize_goal_status("active") or "active",
            "objective": text,
            "created_at": iso_now,
            "updated_at": iso_now,
            "source": "long_task",
        }
        summary = _clean_ui_summary(ui_summary)
        if summary:
            blob["ui_summary"] = summary
        if isinstance(existing, dict):
            blob["replaced_at"] = iso_now
            blob["previous_objective"] = existing.get("objective")
        md[GOAL_STATE_KEY] = blob
        md["goal_started_at"] = epoch_now
        discard_legacy_goal_state_key(md)
        reset_goal_continuation_marker(md)
        clear_goal_waiting(md)
        session.metadata = md
        _persist_session(self._tool_ctx, session)

        _publish(
            self._tool_ctx,
            channel=self._channel,
            chat_id=self._chat_id,
            session_key=getattr(session, "session_key", None),
            metadata=md,
        )

        return (
            f"Goal recorded (status=active). Continue toward the objective "
            f"and call `complete_goal` when done.\n\nObjective:\n{text}"
        )


# ---------------------------------------------------------------------------
# CompleteGoalTool
# ---------------------------------------------------------------------------


@tool_parameters(
    tool_parameters_schema(
        action=StringSchema(
            "Final action for the goal: complete | cancel | block | replace.",
            enum=GOAL_ACTIONS,
        ),
        recap=StringSchema(
            "For `complete`: short summary of what was achieved.",
            max_length=8000,
            nullable=True,
        ),
        objective=StringSchema(
            "For `replace`: the new objective that supersedes the current one.",
            max_length=MAX_GOAL_OBJECTIVE_CHARS,
            nullable=True,
        ),
        ui_summary=StringSchema(
            "For `replace`: optional short label for the new objective.",
            max_length=120,
            nullable=True,
        ),
        required=["action"],
    )
)
class CompleteGoalTool(Tool, ContextAware):
    """Complete, cancel, block, or replace the active sustained goal."""

    name = "complete_goal"
    description = (
        "Close out the active sustained goal. Use `complete` when the work "
        "is done, `cancel` to abandon it, `block` when you need a human or "
        "orchestrator decision before proceeding, or `replace` to swap the "
        "objective. After any terminal action (complete/cancel/block) the "
        "agent returns to default one-shot behavior until a new `long_task` "
        "is recorded."
    )

    def __init__(self) -> None:
        self._channel = ""
        self._chat_id = ""
        self._tool_ctx: ToolContext | None = None

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        tool = cls()
        tool._tool_ctx = ctx
        return tool

    def set_context(self, ctx: RequestContext) -> None:
        self._channel = ctx.channel
        self._chat_id = ctx.chat_id

    def has_capability(self, capability: str) -> bool:
        return capability in {"goal-management", "long-running"}

    def get_capabilities(self) -> list[str]:
        return ["goal-management", "long-running"]

    async def execute(
        self,
        action: str,
        recap: str | None = None,
        objective: str | None = None,
        ui_summary: str | None = None,
    ) -> str:
        action_norm = (action or "").strip().lower()
        if action_norm not in GOAL_ACTIONS:
            return (
                f"Error: unknown action {action!r}. "
                f"Valid actions: {', '.join(GOAL_ACTIONS)}."
            )

        if self._tool_ctx is None:
            return "Error: tool context not bound; cannot update goal."
        session = _resolve_session(self._tool_ctx, self._channel, self._chat_id)
        if session is None:
            return "Error: no active session — cannot update the goal."

        md = dict(session.metadata or {})
        blob = parse_goal_state(md.get(GOAL_STATE_KEY))
        if not isinstance(blob, dict):
            blob = {"status": "active"}

        # Resolve the existing status once so we can give a precise error.
        existing_status = normalize_goal_status(blob.get("status"))

        # ``replace`` is the explicit recovery path: it bootstraps a fresh
        # goal regardless of the previous state, as long as mutation
        # permission is granted further down.
        if action_norm == "replace":
            pass  # fall through to the replace branch below
        elif existing_status in {"completed", "cancelled", "blocked"}:
            # Goal is in a terminal state — refuse to silently rewrite
            # history; ask the caller to use ``replace`` if they want to
            # start over.
            return (
                f"Error: goal is already {existing_status}. "
                "Use action='replace' to start a fresh objective or omit the call."
            )
        elif not sustained_goal_active(md):
            # No active goal and no terminal state either (truly empty session).
            return "Error: no active goal to update."

        epoch_now = _now_epoch()
        iso_now = _now_iso_ms()
        blob["updated_at"] = iso_now

        # Sanitize the optional ``recap`` field — strip whitespace and
        # cap at 8000 characters to match the tool schema's
        # ``max_length``.  Without this cap a runaway LLM could fill
        # session metadata with megabytes of recap text.
        clean_recap: str | None = None
        if recap:
            if not isinstance(recap, str):
                return "Error: 'recap' must be a string."
            stripped = recap.strip()
            if stripped:
                clean_recap = stripped[:8000]

        if action_norm == "complete":
            blob["status"] = "completed"
            blob["completed_at"] = iso_now
            if clean_recap is not None:
                blob["recap"] = clean_recap
            md[GOAL_STATE_KEY] = blob
            discard_legacy_goal_state_key(md)
            clear_goal_waiting(md)
            session.metadata = md
            _persist_session(self._tool_ctx, session)
            revoke_goal_mutation_permission()
        elif action_norm == "cancel":
            blob["status"] = "cancelled"
            blob["cancelled_at"] = iso_now
            if clean_recap is not None:
                blob["cancel_reason"] = clean_recap
            md[GOAL_STATE_KEY] = blob
            discard_legacy_goal_state_key(md)
            clear_goal_waiting(md)
            session.metadata = md
            _persist_session(self._tool_ctx, session)
            revoke_goal_mutation_permission()
        elif action_norm == "block":
            blob["status"] = "blocked"
            blob["blocked_at"] = iso_now
            if clean_recap is not None:
                md["goal_block_reason"] = clean_recap
            md[GOAL_STATE_KEY] = blob
            discard_legacy_goal_state_key(md)
            session.metadata = md
            _persist_session(self._tool_ctx, session)
            revoke_goal_mutation_permission()
        elif action_norm == "replace":
            try:
                require_goal_mutation_permission()
            except GoalMutationNotAllowedError as exc:
                return str(exc)
            text, err = _validate_objective(objective)
            if err:
                return err
            if _self_containment_required(self._tool_ctx) and not is_self_contained_objective(text):
                return (
                    "Error: replacement 'objective' looks like an "
                    "open-ended question. Reframe and retry."
                )
            blob["previous_objective"] = blob.get("objective")
            blob["objective"] = text
            blob["replaced_at"] = iso_now
            blob["status"] = "active"
            summary = _clean_ui_summary(ui_summary)
            if summary:
                blob["ui_summary"] = summary
            md[GOAL_STATE_KEY] = blob
            md["goal_started_at"] = epoch_now
            discard_legacy_goal_state_key(md)
            reset_goal_continuation_marker(md)
            clear_goal_waiting(md)
            session.metadata = md
            _persist_session(self._tool_ctx, session)
        else:  # pragma: no cover - defensive
            return f"Error: unsupported action {action_norm!r}"

        _publish(
            self._tool_ctx,
            channel=self._channel,
            chat_id=self._chat_id,
            session_key=getattr(session, "session_key", None),
            metadata=session.metadata,
        )

        if action_norm in GOAL_FINAL_ACTIONS:
            return f"Goal {action_norm}. Default one-shot behavior is restored."
        return f"Goal replaced. Continue working toward:\n{objective}"


# ---------------------------------------------------------------------------
# Convenience helpers (used by slash commands and tests)
# ---------------------------------------------------------------------------


def current_goal_blob(metadata: dict[str, Any]) -> dict[str, Any] | None:
    """Return the session's current goal blob, or ``None``."""
    blob = parse_goal_state(metadata.get(GOAL_STATE_KEY))
    return blob if isinstance(blob, dict) else None


def is_replace_allowed() -> bool:
    """Predicate for callers that need to decide between ``replace`` and ``block``."""
    return goal_mutation_allowed()


__all__ = [
    "LongTaskTool",
    "CompleteGoalTool",
    "current_goal_blob",
    "is_replace_allowed",
]