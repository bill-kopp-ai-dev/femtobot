"""Runtime support for HTTP-level goal tracking.

This module is the data-model side of the ``async_goal`` contract; it
does *not* touch the HTTP server.  The caller (the API request handler,
the goal events stream) feeds events in and reads the public surface
out.

It is intentionally side-effect free so it can be unit-tested in
isolation.
"""

from __future__ import annotations

import json
import secrets
import string
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping


_JOB_ID_ALPHABET = string.ascii_letters + string.digits
_EVENT_ID_ALPHABET = string.ascii_letters + string.digits


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _parse_iso(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp string into a UTC ``datetime``.

    Accepts strings ending in ``Z`` (the canonical form we emit), with
    or without a timezone suffix.  Non-string values and malformed
    strings return ``None`` instead of raising — callers treat this as
    "no reliable timestamp".
    """
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def generate_goal_id() -> str:
    """Stable, opaque id used by the API to address one long-task job."""
    return "goal_" + "".join(secrets.choice(_JOB_ID_ALPHABET) for _ in range(16))


def generate_event_id() -> str:
    """Stable, opaque id used by the API to address one event row."""
    return "evt_" + "".join(secrets.choice(_EVENT_ID_ALPHABET) for _ in range(16))


class GoalJobStatus(str, Enum):
    """Lifecycle of a goal job as seen by an HTTP caller.

    Distinct from the in-session goal ``status`` (active/completed/...) —
    a ``GoalJobStatus`` is a transport-level state, while the goal blob
    itself is the worker-level state.
    """

    ACCEPTED = "accepted"  # request admitted; goal being created/started
    RUNNING = "running"  # goal is active; runner is in flight
    WAITING = "waiting"  # waiting on ask_orchestrator response
    COMPLETE = "complete"  # goal terminated successfully
    CANCELLED = "cancelled"  # user / supervisor terminated the goal
    BLOCKED = "blocked"  # goal hit a guardrail and is awaiting decision
    FAILED = "failed"  # unexpected error during execution


TERMINAL_STATUSES: frozenset[GoalJobStatus] = frozenset(
    {
        GoalJobStatus.COMPLETE,
        GoalJobStatus.CANCELLED,
        GoalJobStatus.BLOCKED,
        GoalJobStatus.FAILED,
    }
)


class GoalEventKind(str, Enum):
    """Kinds of events the API may surface for a goal job."""

    CREATED = "goal_created"
    STATUS_CHANGED = "status_changed"
    ASK_PENDING = "ask_pending"
    ASK_ANSWERED = "ask_answered"
    ASK_TIMED_OUT = "ask_timed_out"
    ITERATION = "iteration"  # per-iteration progress marker
    LOG = "log"  # arbitrary text log
    FINAL = "final"  # terminal summary; mirrors the last user-visible content


@dataclass
class GoalEvent:
    """A single event row associated with a goal job."""

    event_id: str
    goal_id: str
    kind: GoalEventKind
    occurred_at: str
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def new(
        cls,
        *,
        goal_id: str,
        kind: GoalEventKind,
        data: dict[str, Any] | None = None,
    ) -> "GoalEvent":
        return cls(
            event_id=generate_event_id(),
            goal_id=goal_id,
            kind=kind,
            occurred_at=_utc_now_iso(),
            data=data or {},
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind.value if isinstance(self.kind, GoalEventKind) else self.kind
        return d

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GoalEvent":
        kind_raw = payload.get("kind") or GoalEventKind.LOG.value
        try:
            kind_enum = GoalEventKind(kind_raw)
        except ValueError:
            kind_enum = GoalEventKind.LOG
        return cls(
            event_id=str(payload.get("event_id") or generate_event_id()),
            goal_id=str(payload.get("goal_id") or ""),
            kind=kind_enum,
            occurred_at=str(payload.get("occurred_at") or _utc_now_iso()),
            data=dict(payload.get("data") or {}),
        )


@dataclass
class GoalJob:
    """Public, transport-level view of a long-task job."""

    goal_id: str
    session_key: str
    status: GoalJobStatus = GoalJobStatus.ACCEPTED
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)
    objective: str | None = None
    correlation_id: str | None = None  # optional pre-existing ask id
    events: list[GoalEvent] = field(default_factory=list)
    final_content: str | None = None
    error: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def elapsed_s(self, *, now: datetime | None = None) -> float:
        started = _parse_iso(self.created_at)
        if not started:
            return 0.0
        current = now or datetime.now(timezone.utc)
        return max(0.0, (current - started).total_seconds())

    def to_dict(self, *, include_events: bool = False) -> dict[str, Any]:
        d = {
            "goal_id": self.goal_id,
            "session_key": self.session_key,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "objective": self.objective,
            "correlation_id": self.correlation_id,
            "elapsed_s": self.elapsed_s(),
            "final_content": self.final_content,
            "error": self.error,
        }
        if include_events:
            d["events"] = [e.to_dict() for e in self.events]
        return d

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GoalJob":
        try:
            status = GoalJobStatus(payload.get("status") or GoalJobStatus.ACCEPTED.value)
        except ValueError:
            status = GoalJobStatus.ACCEPTED
        events_raw = payload.get("events") or []
        events = [
            GoalEvent.from_dict(e) if isinstance(e, Mapping) else GoalEvent.new(goal_id="")
            for e in events_raw
        ]
        return cls(
            goal_id=str(payload.get("goal_id") or generate_goal_id()),
            session_key=str(payload.get("session_key") or ""),
            status=status,
            created_at=str(payload.get("created_at") or _utc_now_iso()),
            updated_at=str(payload.get("updated_at") or _utc_now_iso()),
            objective=payload.get("objective"),
            correlation_id=payload.get("correlation_id"),
            events=events,
            final_content=payload.get("final_content"),
            error=payload.get("error"),
        )


def create_goal_job(
    *,
    session_key: str,
    objective: str | None = None,
    correlation_id: str | None = None,
) -> GoalJob:
    """Factory that mints a new job with a fresh ``goal_id``."""
    return GoalJob(
        goal_id=generate_goal_id(),
        session_key=session_key,
        objective=objective,
        correlation_id=correlation_id,
    )


def serialize_goal_event(event: GoalEvent) -> str:
    """NDJSON-ready serialization (one event per line)."""
    return json.dumps(event.to_dict(), separators=(",", ":"))


def terminal_status(status: GoalJobStatus | str) -> bool:
    """Convenience predicate — True if the goal has reached a terminal state."""
    try:
        enum = status if isinstance(status, GoalJobStatus) else GoalJobStatus(status)
    except ValueError:
        return False
    return enum in TERMINAL_STATUSES


def merge_events(*streams: Iterable[GoalEvent]) -> list[GoalEvent]:
    """Merge multiple event streams, sorted by ``occurred_at``.

    Falls back to ``event_id`` (a random opaque id we mint at creation
    time) as a stable tie-breaker so two events sharing the exact same
    timestamp keep the order in which they were minted.
    """
    flat: list[GoalEvent] = []
    for s in streams:
        flat.extend(s)
    flat.sort(key=lambda e: ((e.occurred_at or ""), (e.event_id or "")))
    return flat