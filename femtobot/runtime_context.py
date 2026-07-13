"""Runtime context blocks injected into the system prompt.

A :class:`RuntimeContextBlock` is a typed, source-tagged chunk of text
that the loop appends to the system prompt during :meth:`ContextBuilder
.build_system_prompt`.  Multiple blocks can coexist (goal active,
pending ask, blocked goal) without polluting each other's content.

The module is purely functional — no I/O — so unit tests can exercise
it without spinning up an event loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, List, Mapping

from femtobot.session.goal_state import (
    goal_block_reason,
    goal_id,
    goal_started_at,
    goal_state_runtime_lines,
    goal_waiting_on,
)
from femtobot.session.pending_asks import AskStatus, AskTarget, list_pending_asks


@dataclass(frozen=True)
class RuntimeContextBlock:
    """A typed chunk of runtime context for the system prompt."""

    source: str  # e.g. "goal", "ask_pending", "goal_blocked"
    lines: tuple[str, ...]

    def to_text(self) -> str:
        """Render as a single string with a header and trailing newline."""
        header = f"[runtime:{self.source}]"
        body = "\n".join(self.lines).rstrip()
        return f"{header}\n{body}\n" if body else f"{header}\n"


def goal_active_block(metadata: Mapping[str, Any] | None) -> RuntimeContextBlock | None:
    """Block for the active goal — uses the existing runtime lines helper."""
    lines = goal_state_runtime_lines(metadata)
    if not lines:
        return None
    extras: list[str] = []
    gid = goal_id(metadata)
    started = goal_started_at(metadata)
    if gid:
        extras.append(f"Goal id: {gid}")
    if started is not None:
        # Convert epoch seconds → human-readable UTC ISO-8601 so the LLM
        # can read the wall-clock time directly.  Sub-second precision is
        # preserved at the millisecond level.
        iso = (
            datetime.fromtimestamp(started, tz=timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        extras.append(f"Started at (UTC): {iso}")
    return RuntimeContextBlock(
        source="goal",
        lines=tuple(lines + extras),
    )


def ask_pending_block(metadata: Mapping[str, Any] | None) -> RuntimeContextBlock | None:
    """Block listing pending orchestrator asks — drives the resume flow."""
    asks = [a for a in list_pending_asks(metadata) if a.status is AskStatus.PENDING]
    if not asks:
        return None
    lines = ["Pending asks (orchestrator must answer to resume):"]
    for a in asks:
        # ``target`` is typed as ``AskTarget``; ``.value`` is the
        # canonical lowercase string ("orchestrator" / "human").
        target = (
            a.target.value
            if isinstance(a.target, AskTarget)
            else str(a.target)
        )
        lines.append(f"  - correlation_id={a.correlation_id} target={target}")
        lines.append(f"    question: {a.question}")
        if a.context:
            lines.append(f"    context: {a.context[:200]}")
        if a.options:
            lines.append(f"    options: {', '.join(a.options)}")
        lines.append(f"    deadline_at: {a.deadline_at}")
    return RuntimeContextBlock(source="ask_pending", lines=tuple(lines))


def goal_blocked_block(metadata: Mapping[str, Any] | None) -> RuntimeContextBlock | None:
    """Block shown when the goal is blocked waiting for human decision."""
    if not metadata:
        return None
    # Use the typed helper so non-string payloads (e.g. legacy ``bytes``
    # values in session metadata) are filtered consistently with the
    # rest of the goal-state machinery.
    if goal_waiting_on(metadata) != "ask_orchestrator":
        return None
    lines = ["Goal is blocked waiting on orchestrator/human input."]
    reason = goal_block_reason(metadata)
    if reason:
        lines.append(f"Reason: {reason}")
    waiting = goal_waiting_on(metadata)
    if waiting:
        lines.append(f"Waiting on: {waiting}")
    return RuntimeContextBlock(source="goal_blocked", lines=tuple(lines))


def build_runtime_context_blocks(
    metadata: Mapping[str, Any] | None,
    *,
    include_pending_asks: bool = True,
) -> list[RuntimeContextBlock]:
    """Compose the full set of blocks for a session."""
    blocks: list[RuntimeContextBlock] = []
    goal_block = goal_active_block(metadata)
    if goal_block is not None:
        blocks.append(goal_block)
    blocked_block = goal_blocked_block(metadata)
    if blocked_block is not None:
        blocks.append(blocked_block)
    if include_pending_asks:
        ask_block = ask_pending_block(metadata)
        if ask_block is not None:
            blocks.append(ask_block)
    return blocks


def render_runtime_context(
    metadata: Mapping[str, Any] | None,
    *,
    include_pending_asks: bool = True,
) -> str:
    """Return the concatenated text of every block for the current session."""
    blocks = build_runtime_context_blocks(
        metadata, include_pending_asks=include_pending_asks
    )
    return "\n".join(b.to_text() for b in blocks)


def merge_block_lines(blocks: Iterable[RuntimeContextBlock]) -> List[str]:
    """Helper for callers that prefer a flat list of lines."""
    out: List[str] = []
    for block in blocks:
        out.append(f"[runtime:{block.source}]")
        out.extend(block.lines)
    return out


__all__ = [
    "RuntimeContextBlock",
    "goal_active_block",
    "ask_pending_block",
    "goal_blocked_block",
    "build_runtime_context_blocks",
    "render_runtime_context",
    "merge_block_lines",
]