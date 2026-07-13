"""``ask_orchestrator`` — blocking tool for orchestrator/human input.

When the worker hits a critical decision it should NOT guess, this tool:

1. Generates a ``correlation_id`` and persists the pending ask in session
   metadata (so it survives a restart).
2. Sends an outbound message to the orchestrator channel (or the current
   channel when ``escalation_channel`` is unset).
3. If ``blocking=True`` (default), returns a short string and the agent
   turn ends — the next inbound on the same session (with matching
   ``correlation_id``) resumes the goal.
4. Marks the goal as ``waiting_on="ask_orchestrator"`` so the runtime
   context shows the pending ask in the system prompt.

The answer is delivered by:

* ``POST /v1/goals/{goal_id}/answer`` (HTTP) — M5's
  :mod:`femtobot.api.goal_handlers`.
* A slash command / slash-equivalent reply with ``correlation_id`` in
  metadata — handled by the loop when the inbound lands.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from femtobot.agent.tools.base import Tool, tool_parameters
from femtobot.agent.tools.context import ContextAware, RequestContext, ToolContext
from femtobot.agent.tools.schema import StringSchema, tool_parameters_schema
from femtobot.bus.events import OutboundMessage
from femtobot.session.goal_state import (
    clear_goal_waiting,
    goal_waiting_on,
    mark_goal_waiting,
    sustained_goal_active,
)
from femtobot.session.pending_asks import (
    AskStatus,
    AskTarget,
    PendingAsk,
    append_pending_ask,
    count_pending_asks,
    deadline_iso,
    generate_correlation_id,
    validate_question_payload,
)


def _now_iso_ms() -> str:
    """Return the current UTC time as an ISO-8601 string with millisecond precision.

    Centralized so ``created_at`` and ``deadline_at`` are derived from the
    exact same instant — avoids the off-by-microsecond window that
    occurred when ``time.strftime`` and ``time.gmtime`` were called twice
    in sequence.
    """
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_session(ctx: ToolContext, channel: str, chat_id: str) -> Any:
    sessions = getattr(ctx, "sessions", None)
    if sessions is None:
        return None
    return sessions.get_or_create(f"{channel}:{chat_id}")


def _pick_target(value: str | None) -> AskTarget:
    if isinstance(value, str):
        norm = value.strip().lower()
        if norm == "human":
            return AskTarget.HUMAN
    return AskTarget.ORCHESTRATOR


def _resolve_channel(ctx: ToolContext, default_channel: str) -> str:
    """Pick the destination channel from ``ctx.long_task_config.escalation_channel``."""
    cfg = getattr(ctx, "long_task_config", None)
    if cfg is None:
        return default_channel
    ch = getattr(cfg, "escalation_channel", None)
    return ch or default_channel


def _resolve_chat_id(ctx: ToolContext, default_chat_id: str) -> str:
    cfg = getattr(ctx, "long_task_config", None)
    if cfg is None:
        return default_chat_id
    return getattr(cfg, "escalation_chat_id", None) or default_chat_id


def _check_ask_budget(
    metadata: dict[str, Any],
    *,
    max_attempts: int,
) -> str | None:
    """Return None if under the cap, otherwise an error string."""
    if max_attempts <= 0:
        return None
    if count_pending_asks(metadata) >= max_attempts:
        return (
            f"Error: ask_orchestrator budget exhausted ({max_attempts} per goal). "
            "Use the best available hypothesis or call `complete_goal(action='block')`."
        )
    return None


def _ask_max_attempts(ctx: ToolContext) -> int:
    cfg = getattr(ctx, "long_task_config", None)
    if cfg is None:
        return 3
    try:
        return int(getattr(cfg, "max_goal_ask_attempts", 3))
    except (TypeError, ValueError):
        return 3


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


@tool_parameters(
    tool_parameters_schema(
        question=StringSchema(
            "Concrete, decision-shaped question that the orchestrator/human can answer. "
            "Avoid open-ended prompts — frame the question so each option is unambiguous.",
            min_length=1,
            max_length=4000,
        ),
        context=StringSchema(
            "Optional supporting context — a short paragraph or list of facts. "
            "Max 8 000 characters.",
            max_length=8000,
            nullable=True,
        ),
        options=StringSchema(
            "Optional comma-separated list of suggested answers. Each option is "
            "labelled as `index|text` so the orchestrator can pick by index.",
            max_length=4000,
            nullable=True,
        ),
        timeoutS=StringSchema(
            "Maximum seconds to wait for the orchestrator/human to respond before "
            "timing out. Range: 30..86400. Default 1800.",
            max_length=8,
            nullable=True,
        ),
        blocking=StringSchema(
            "When true (default), the turn ends after this call and resumes when the "
            "answer arrives. When false, the call returns immediately with a marker "
            "and the agent must continue under uncertainty.",
            max_length=8,
            nullable=True,
        ),
        target=StringSchema(
            "Audience for the question. `orchestrator` (default) routes to the "
            "configured supervisor channel; `human` routes to the current chat.",
            max_length=16,
            nullable=True,
        ),
        required=["question"],
    )
)
class AskOrchestratorTool(Tool, ContextAware):
    """Pause the goal to ask the orchestrator (or human) a critical question."""

    name = "ask_orchestrator"
    description = (
        "Block and ask the orchestrator (or human) for a critical decision. "
        "Use this when the next step requires user/operator approval, when "
        "two strategies are mutually exclusive, or when the model is "
        "guessing and the guess is too expensive to undo. Do NOT use this "
        "for casual clarification — it consumes one of the goal's ask "
        "budgets and may stall the worker until a reply arrives."
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
        return capability in {"orchestrator", "long-running"}

    def get_capabilities(self) -> list[str]:
        return ["orchestrator", "long-running"]

    async def execute(
        self,
        question: str,
        context: str | None = None,
        options: str | None = None,
        timeoutS: str | None = None,
        blocking: str | None = None,
        target: str | None = None,
    ) -> str:
        if self._tool_ctx is None:
            return "Error: tool context not bound; cannot ask orchestrator."

        # Normalize optional parameters.  We accept string inputs to keep the
        # schema minimal — the LLM will typically pass raw values.
        def _to_bool(value: Any, default: bool) -> bool:
            if value is None:
                return default
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().lower() in {"true", "1", "yes", "y", "on"}
            if isinstance(value, (int, float)):
                return bool(value)
            return default

        def _to_int(value: Any, default: int) -> int:
            # Reject bool explicitly — ``int(True) == 1`` would silently
            # turn a stray ``true`` flag into a 1-second timeout.
            if isinstance(value, bool) or value is None:
                return default
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        timeout_value = _to_int(timeoutS, 1800)
        blocking_value = _to_bool(blocking, True)

        err = validate_question_payload(
            question=question, context=context, timeout_s=timeout_value
        )
        if err:
            return err

        session = _resolve_session(self._tool_ctx, self._channel, self._chat_id)
        if session is None:
            return "Error: no active session — cannot ask orchestrator."

        md = dict(session.metadata or {})
        if not sustained_goal_active(md):
            return (
                "Error: ask_orchestrator requires an active sustained goal. "
                "Bootstrap one with `long_task` or `/goal <objective>` first."
            )

        budget_err = _check_ask_budget(
            md, max_attempts=_ask_max_attempts(self._tool_ctx)
        )
        if budget_err:
            return budget_err

        # Parse options — accept either newlines or commas as separators.
        # Cap the number of options at 100 so a runaway LLM cannot fill
        # session metadata with megabytes of garbage.
        _MAX_OPTIONS = 100
        _MAX_OPTION_CHARS = 200
        options_list: list[str] = []
        if options:
            for line in re.split(r"[,\n]", str(options)):
                line = line.strip()
                if not line:
                    continue
                if len(line) > _MAX_OPTION_CHARS:
                    line = line[:_MAX_OPTION_CHARS].rstrip()
                options_list.append(line)
                if len(options_list) >= _MAX_OPTIONS:
                    break

        target_enum = _pick_target(target)
        correlation_id = generate_correlation_id()
        # Use a single timestamp source so ``created_at`` and
        # ``deadline_at`` are derived from the exact same instant.
        created_at_iso = _now_iso_ms()
        ask = PendingAsk(
            correlation_id=correlation_id,
            target=target_enum,
            question=question.strip(),
            context=context.strip() if isinstance(context, str) and context else None,
            options=options_list,
            created_at=created_at_iso,
            deadline_at=deadline_iso(
                created_at=created_at_iso,
                timeout_s=timeout_value,
            ),
            session_key=getattr(session, "session_key", None),
            status=AskStatus.PENDING,
        )
        append_pending_ask(md, ask)
        mark_goal_waiting(
            md,
            waiting_on="ask_orchestrator",
            correlation_id=correlation_id,
        )
        session.metadata = md
        # Persist the ask so a crash between the tool call and the next
        # inbound doesn't lose the operator's pending question.
        try:
            sessions = getattr(self._tool_ctx, "sessions", None)
            if sessions is not None:
                sessions.save(session)
        except Exception:
            pass

        # Build the outbound message — routes via the escalation channel
        # when configured.
        dest_channel = _resolve_channel(self._tool_ctx, self._channel)
        dest_chat_id = _resolve_chat_id(self._tool_ctx, self._chat_id)
        body = (
            f"[ask_orchestrator] {question.strip()}\n\n"
            f"correlation_id: `{correlation_id}`\n"
            f"target: {target_enum.value}\n"
            f"deadline_at: {ask.deadline_at}"
        )
        if options_list:
            body += "\n\nOptions:\n" + "\n".join(
                f"  - `{i}` {opt}" for i, opt in enumerate(options_list)
            )
        if context:
            body += f"\n\nContext:\n{context.strip()[:1500]}"
        outbound = OutboundMessage(
            channel=dest_channel,
            chat_id=dest_chat_id,
            content=body,
            metadata={
                "render_as": "text",
                "ask_correlation_id": correlation_id,
                "ask_target": target_enum.value,
                "ask_session_key": getattr(session, "session_key", ""),
                "ask_deadline_at": ask.deadline_at or "",
            },
        )
        bus = getattr(self._tool_ctx, "bus", None)
        if bus is not None and hasattr(bus, "publish_outbound"):
            try:
                await bus.publish_outbound(outbound)
            except (RuntimeError, asyncio.TimeoutError, ConnectionError) as exc:
                # Transport-level failures are non-fatal for the ask itself;
                # the goal still has the persisted ask and may be answered
                # via API.  Other exceptions (TypeError, AttributeError, …)
                # are programmer errors and must propagate.
                logger.warning(
                    "ask_orchestrator outbound publish failed ({}); "
                    "goal remains answerable via API.",
                    exc,
                )

        if blocking_value:
            return (
                f"Ask sent (correlation_id={correlation_id}). The goal is "
                "now blocked waiting on the orchestrator. The next inbound on "
                "this session that includes the correlation_id will resume "
                "the goal."
            )
        return (
            f"Ask sent (correlation_id={correlation_id}, non-blocking). "
            "Continue with the most likely hypothesis; the orchestrator may "
            "still reply later."
        )


__all__ = [
    "AskOrchestratorTool",
    "_check_ask_budget",
    "_resolve_channel",
    "_resolve_chat_id",
    "_ask_max_attempts",
]