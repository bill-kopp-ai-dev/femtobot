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

from pydantic import BaseModel, Field, field_validator


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
        """Reject messages that reference internal file names."""
        forbidden = ("HEARTBEAT.md", "AWARENESS.md", "AGENTS.md", "SOUL.md")
        for token in forbidden:
            if token in v:
                raise ValueError(
                    f"final_message references internal file {token!r}. "
                    "Strip internal references before delivering to the user."
                )
        return v


__all__ = ["FemtobotOutput"]
