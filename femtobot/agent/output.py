"""Validated, Pydantic-typed output of a Femtobot agent run.

Replaces the loose ``runner.py`` constants (EMPTY_FINAL_RESPONSE_MESSAGE,
PERSISTED_MODEL_ERROR_PLACEHOLDER, _MAX_EMPTY_RETRIES, ...) with a
typed model. PydanticAI runs ``output_validator`` after the model
emits a candidate output, giving us reflection-on-error for free.

Femtobot 1.0 (Phase 1) — this model is consumed by the PydanticAI
Agent. The legacy Runner that produced ad-hoc dict returns continues
to be used by the AgentLoop until Phase 4.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

# Bug fix (re-audit 2026-07-18): the previous substring match for
# ``AGENTS.md`` blocked legitimate messages like "Your personalized
# notes live in AGENTS.md" or "femtobot uses AGENTS.md for identity".
# The regex below only flags *path-like* references: the token must
# be preceded by ``/``, ``./``, or ``../`` (typical of path
# components). Plain prose mentions — where the filename is preceded
# by a space or sits at the start of a sentence — are accepted.
# Path-prefix alternatives (alternation must be inside the group).
_INTERNAL_FILE_LEAK_RE = re.compile(
    r"(?:/|\./|\.\./|\.femtobot/)"
    r"(?:agents|soul|heartbeat|awareness)\.md\b",
    re.IGNORECASE,
)


class FemtobotOutput(BaseModel):
    """A single, validated agent response."""

    final_message: str = Field(
        description="The text the model wants to deliver to the user."
    )
    iterations_used: int = Field(
        default=0,
        description="Number of model→tool→model iterations consumed.",
    )
    completed_goal: bool = Field(
        default=False,
        description="Whether the agent considers the goal achieved.",
    )

    @field_validator("final_message")
    @classmethod
    def not_empty(cls, v: str) -> str:
        """Reject empty final messages — the model should retry."""
        if not v or not v.strip():
            raise ValueError(
                "Empty final_message. The agent must produce a non-empty "
                "response or call a tool to continue."
            )
        return v

    @field_validator("final_message")
    @classmethod
    def no_internal_leakage(cls, v: str) -> str:
        """Reject messages that leak internal file paths.

        Bug fix (re-audit 2026-07-18): the original substring check
        matched ``"AGENTS.md"`` inside plain prose, blocking any
        legitimate mention of these files (e.g. "edit AGENTS.md to
        customize your identity"). The new regex only flags
        *path-like* references where the filename is preceded by ``/``
        or ``./``, which is what an actual leak from a tool result
        looks like.
        """
        match = _INTERNAL_FILE_LEAK_RE.search(v)
        if match is not None:
            raise ValueError(
                f"final_message leaks internal file path containing {match.group(0)!r}. "
                "Strip the path reference before delivering to the user."
            )
        return v


__all__ = ["FemtobotOutput"]
