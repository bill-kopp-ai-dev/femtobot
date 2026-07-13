"""Persistence helpers for blocking ``ask_orchestrator`` calls.

When the worker pauses to ask the orchestrator/human a question, the
pending ask is recorded in the session metadata so it survives restarts
and can be correlated with the eventual answer. This module is
intentionally side-effect free — readers and writers must be invoked by
the caller (the tool, the API endpoint, the runtime event publisher).

Schema (under ``session.metadata["pending_asks"]``):

.. code-block:: json

    {
      "correlation_id": "ask_2025-07-13T12:34:56Z_abcd",
      "target": "orchestrator" | "human",
      "question": "…",
      "context": "…",
      "options": ["A", "B"],
      "status": "pending" | "answered" | "timed_out" | "cancelled",
      "created_at": "2025-07-13T12:34:56.789Z",
      "deadline_at": "2025-07-13T13:04:56.789Z",
      "answered_at": null,
      "response": null,
      "goal_id": null,
      "session_key": "api:default"
    }
"""

from __future__ import annotations

import json
import re
import secrets
import string
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping, MutableMapping

PENDING_ASKS_KEY = "pending_asks"

# Maximum size for a single ask's ``question`` field.  Matches the tool
# schema's ``max_length`` and the orchestrator's expected reply envelope.
_MAX_PENDING_ASK_QUESTION_CHARS = 4000
# Maximum size for a single ask's ``context`` field (the supporting
# paragraph).  Twice the question cap because context is auxiliary.
_MAX_PENDING_ASK_CONTEXT_CHARS = 8000
# Upper bound for ask deadlines — keeps a runaway ask from sitting in
# the session forever after the orchestrator disappears.
_MAX_ASK_DEADLINE_S = 86_400  # 24h


class AskStatus(str, Enum):
    """Lifecycle of a blocking ask."""

    PENDING = "pending"
    ANSWERED = "answered"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class AskTarget(str, Enum):
    """Who the ask is routed to."""

    ORCHESTRATOR = "orchestrator"
    HUMAN = "human"


_ID_ALPHABET = string.ascii_letters + string.digits
_CORRELATION_PREFIX = "ask_"


def _utc_now_iso() -> str:
    """ISO-8601 UTC timestamp with millisecond precision."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def generate_correlation_id() -> str:
    """Return a new unique id with the ``ask_`` prefix."""
    suffix = "".join(secrets.choice(_ID_ALPHABET) for _ in range(12))
    return f"{_CORRELATION_PREFIX}{suffix}"


def _parse_iso(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def deadline_iso(*, created_at: str, timeout_s: int) -> str:
    """Compute the ``deadline_at`` timestamp given a base and a TTL in seconds."""
    from datetime import timedelta

    base = _parse_iso(created_at) or datetime.now(timezone.utc)
    return (base + timedelta(seconds=float(timeout_s))).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")


@dataclass
class PendingAsk:
    """A blocking ask recorded in session metadata."""

    correlation_id: str
    target: AskTarget
    question: str
    context: str | None = None
    options: list[str] = field(default_factory=list)
    status: AskStatus = AskStatus.PENDING
    created_at: str = field(default_factory=_utc_now_iso)
    deadline_at: str | None = None
    answered_at: str | None = None
    response: str | None = None
    goal_id: str | None = None
    session_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe serialization."""
        d = asdict(self)
        d["target"] = self.target.value if isinstance(self.target, AskTarget) else self.target
        d["status"] = self.status.value if isinstance(self.status, AskStatus) else self.status
        return d

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PendingAsk":
        """Inverse of :meth:`to_dict` — tolerates JSON round-trip."""
        if not isinstance(payload, Mapping):
            raise ValueError(f"PendingAsk.from_dict expected a mapping, got {type(payload).__name__}")
        target = payload.get("target") or AskTarget.ORCHESTRATOR.value
        try:
            target_enum = AskTarget(target)
        except ValueError:
            target_enum = AskTarget.ORCHESTRATOR
        try:
            status_enum = AskStatus(payload.get("status") or AskStatus.PENDING.value)
        except ValueError:
            status_enum = AskStatus.PENDING
        return cls(
            correlation_id=str(payload.get("correlation_id") or ""),
            target=target_enum,
            question=str(payload.get("question") or ""),
            context=payload.get("context"),
            options=list(payload.get("options") or []),
            status=status_enum,
            created_at=str(payload.get("created_at") or _utc_now_iso()),
            deadline_at=payload.get("deadline_at"),
            answered_at=payload.get("answered_at"),
            response=payload.get("response"),
            goal_id=payload.get("goal_id"),
            session_key=payload.get("session_key"),
        )


def _normalize_payload(
    payload: Any,
) -> list[dict[str, Any]]:
    """Return ``payload`` as a list of dicts, defaulting to empty."""
    if not payload:
        return []
    if isinstance(payload, str):
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            return []
        return [d for d in decoded if isinstance(d, dict)] if isinstance(decoded, list) else []
    if isinstance(payload, list):
        return [d for d in payload if isinstance(d, dict)]
    return []


def list_pending_asks(metadata: Mapping[str, Any] | None) -> list[PendingAsk]:
    """Read the asks currently tracked for this session."""
    if not metadata:
        return []
    raw = metadata.get(PENDING_ASKS_KEY)
    return [PendingAsk.from_dict(d) for d in _normalize_payload(raw)]


def find_pending_ask(
    metadata: Mapping[str, Any] | None,
    correlation_id: str,
) -> PendingAsk | None:
    """Locate a single ask by id.

    Returns ``None`` when the ask doesn't exist or has already been
    finalized.  Useful for callers that need to inspect a specific ask
    without iterating the entire pending list.
    """
    for ask in list_pending_asks(metadata):
        if ask.correlation_id == correlation_id:
            return ask
    return None


def append_pending_ask(
    metadata: MutableMapping[str, Any],
    ask: PendingAsk,
) -> None:
    """Append ``ask`` to the session metadata, preserving any existing asks."""
    current = list_pending_asks(metadata)
    current.append(ask)
    metadata[PENDING_ASKS_KEY] = [a.to_dict() for a in current]


def update_pending_ask(
    metadata: MutableMapping[str, Any],
    correlation_id: str,
    *,
    status: AskStatus,
    response: str | None = None,
) -> bool:
    """Apply a status transition to one ask. Returns ``True`` if found."""
    asks = list_pending_asks(metadata)
    changed = False
    now = _utc_now_iso()
    for ask in asks:
        if ask.correlation_id != correlation_id:
            continue
        if ask.status is not AskStatus.PENDING:
            # Already terminal — leave it alone to keep history clean.
            continue
        # Accept both terminal transitions; ``pending`` is treated as a
        # no-op so callers can safely call us after a resume.
        if status is AskStatus.PENDING:
            continue
        ask.status = status
        if status is AskStatus.ANSWERED:
            ask.answered_at = now
            ask.response = response
        elif status is AskStatus.TIMED_OUT:
            ask.answered_at = now
            ask.response = response  # may carry the agent's fallback reasoning
        elif status is AskStatus.CANCELLED:
            ask.answered_at = now
        changed = True
    if changed:
        metadata[PENDING_ASKS_KEY] = [a.to_dict() for a in asks]
    return changed


def expire_pending_asks(
    metadata: MutableMapping[str, Any],
    *,
    now: datetime | None = None,
) -> list[PendingAsk]:
    """Mark expired asks as ``timed_out``. Returns the transitioned asks."""
    asks = list_pending_asks(metadata)
    now = now or datetime.now(timezone.utc)
    expired: list[PendingAsk] = []
    for ask in asks:
        if ask.status is not AskStatus.PENDING:
            continue
        if not ask.deadline_at:
            continue
        deadline = _parse_iso(ask.deadline_at)
        if not deadline:
            continue
        if deadline > now:
            continue
        ask.status = AskStatus.TIMED_OUT
        ask.answered_at = _utc_now_iso()
        expired.append(ask)
    if expired:
        metadata[PENDING_ASKS_KEY] = [a.to_dict() for a in asks]
    return expired


def clear_pending_asks(metadata: MutableMapping[str, Any]) -> None:
    """Remove every tracked ask from the session metadata."""
    metadata.pop(PENDING_ASKS_KEY, None)


def count_pending_asks(metadata: Mapping[str, Any] | None) -> int:
    """Convenience counter — only ``pending`` status counts toward the cap."""
    return sum(1 for a in list_pending_asks(metadata) if a.status is AskStatus.PENDING)


def validate_question_payload(
    *,
    question: str,
    context: str | None,
    timeout_s: int,
) -> str | None:
    """Lightweight payload validation shared by tool, slash command and API."""
    if not isinstance(question, str) or not question.strip():
        return "Error: 'question' is required and must be a non-empty string."
    if len(question) > _MAX_PENDING_ASK_QUESTION_CHARS:
        return (
            f"Error: 'question' exceeds {_MAX_PENDING_ASK_QUESTION_CHARS} chars."
        )
    # Reject non-string ``context`` explicitly — ``str(...)`` would
    # silently coerce ``True`` into ``"True"`` which is meaningless.
    if context is not None and not isinstance(context, str):
        return "Error: 'context' must be a string."
    if context is not None and len(context) > _MAX_PENDING_ASK_CONTEXT_CHARS:
        return (
            f"Error: 'context' exceeds {_MAX_PENDING_ASK_CONTEXT_CHARS} chars."
        )
    if not isinstance(timeout_s, (int, float)):
        return "Error: 'timeoutS' must be a number."
    # ``bool`` is a subclass of ``int``; reject it explicitly so ``True``
    # (timeout_s=1) doesn't silently bypass the bounds check.
    if isinstance(timeout_s, bool) or timeout_s < 30 or timeout_s > _MAX_ASK_DEADLINE_S:
        return (
            f"Error: 'timeoutS' must be between 30 and {_MAX_ASK_DEADLINE_S}."
        )
    return None


_SECURE_ID_RE = re.compile(r"^ask_[A-Za-z0-9]{12,64}$")


def is_valid_correlation_id(value: str | None) -> bool:
    """True when *value* is shaped like a correlation id we previously minted."""
    if not isinstance(value, str):
        return False
    return bool(_SECURE_ID_RE.match(value))


def iter_pending_asks(metadata: Mapping[str, Any] | None) -> Iterable[PendingAsk]:
    """Convenience iterator equivalent to ``list_pending_asks`` but lazy-friendly.

    Note: this helper exists for API symmetry.  Internally it still
    materializes the full list because :class:`PendingAsk.from_dict`
    rebuilds each instance; there is no lazy alternative without
    reshaping the storage format.
    """
    yield from list_pending_asks(metadata)