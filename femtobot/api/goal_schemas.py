"""Request / response models for the ``async_goal`` HTTP contract.

These are intentionally minimal — they only describe the surface the
HTTP layer needs to admit a long-task job and return a status payload.
The runtime side stays in :mod:`femtobot.api.goal_runtime`; the schema
side stays here.

Pydantic is *not* used (femtobot does not import pydantic outside the
config layer) — these dataclasses double as validators and JSON
serializers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")


@dataclass
class AsyncGoalRequest:
    """Inbound payload for ``POST /v1/chat/completions`` with ``async_goal`` enabled."""

    model: str | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)
    session_id: str | None = None
    objective: str | None = None  # pre-supplied long-task objective; skips LLM call
    metadata: dict[str, Any] = field(default_factory=dict)
    stream: bool = False  # SSE streaming response (N/A for async_goal — always 202)

    def validate(self) -> str | None:
        """Return ``None`` when valid, or a human-readable error message."""
        if not self.session_id:
            return "Error: 'session_id' is required for async_goal requests."
        if not _SESSION_ID_RE.match(self.session_id or ""):
            return (
                "Error: 'session_id' must match "
                f"{_SESSION_ID_RE.pattern}."
            )
        if not self.messages and not self.objective:
            return "Error: 'messages' (or 'objective') is required."
        if self.objective is not None and len(self.objective) > 4000:
            return "Error: 'objective' exceeds 4000 characters."
        return None


@dataclass
class AsyncGoalAccepted:
    """Response shape for the HTTP ``202 Accepted`` reply."""

    status: str = "accepted"
    session_id: str = ""
    goal_id: str = ""
    poll_url: str = ""
    events_url: str = ""
    answer_url: str = ""
    accepted_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "session_id": self.session_id,
            "goal_id": self.goal_id,
            "poll_url": self.poll_url,
            "events_url": self.events_url,
            "answer_url": self.answer_url,
            "accepted_at": self.accepted_at,
        }


@dataclass
class AsyncGoalStatus:
    """Response shape for ``GET /v1/goals/{goal_id}``."""

    status: str = "accepted"
    session_id: str = ""
    goal_id: str = ""
    objective: str | None = None
    elapsed_s: float = 0.0
    final_content: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "status": self.status,
            "session_id": self.session_id,
            "goal_id": self.goal_id,
            "elapsed_s": self.elapsed_s,
        }
        if self.objective is not None:
            out["objective"] = self.objective
        if self.final_content is not None:
            out["final_content"] = self.final_content
        if self.error is not None:
            out["error"] = self.error
        return out


@dataclass
class AsyncGoalAnswerRequest:
    """Inbound payload for ``POST /v1/goals/{goal_id}/answer``."""

    correlation_id: str | None = None
    response: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> str | None:
        if not isinstance(self.response, str) or not self.response.strip():
            return "Error: 'response' is required and must be a non-empty string."
        if len(self.response) > 16_000:
            return "Error: 'response' exceeds 16 000 characters."
        return None


def is_valid_session_id(value: str | None) -> bool:
    """Validate a session identifier — same rule as ``AsyncGoalRequest``."""
    return bool(value and _SESSION_ID_RE.match(value))


def chunked(events: Iterable[Any], size: int) -> list[list[Any]]:
    """Split *events* into fixed-size chunks for SSE pagination."""
    out: list[list[Any]] = []
    buf: list[Any] = []
    for e in events:
        buf.append(e)
        if len(buf) >= size:
            out.append(buf)
            buf = []
    if buf:
        out.append(buf)
    return out


__all__ = [
    "AsyncGoalRequest",
    "AsyncGoalAccepted",
    "AsyncGoalStatus",
    "AsyncGoalAnswerRequest",
    "is_valid_session_id",
    "chunked",
]