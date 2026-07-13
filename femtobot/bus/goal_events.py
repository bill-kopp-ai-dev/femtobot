"""Helpers to publish :class:`GoalStateChanged` events.

Wraps the in-process :mod:`femtobot.bus.runtime_events` bus so callers
(slash commands, tools, runtime hooks) don't have to plumb the bus
through every signature.

Idempotent: when no publisher is bound we silently no-op so unit tests
that don't care about the bus don't have to wire one up.
"""

from __future__ import annotations

from typing import Any, Mapping

from loguru import logger

from femtobot.bus.runtime_events import (
    GoalStateChanged,
    RuntimeEventBus,
    RuntimeEventContext,
)

# Module-level reference to the currently active bus.  ``AgentLoop``
# swaps this when it boots so consumers that don't hold a direct bus
# reference can still publish.
_active_bus: RuntimeEventBus | None = None


def set_active_event_bus(bus: RuntimeEventBus | None) -> None:
    """Bind the loop-level bus so module-level publishers can find it."""
    global _active_bus
    _active_bus = bus


def get_active_event_bus() -> RuntimeEventBus | None:
    """Return the currently bound bus, or ``None`` if none is bound."""
    return _active_bus


def publish_goal_state_changed(
    *,
    session_key: str | None = None,
    channel: str,
    chat_id: str,
    session_metadata: Mapping[str, Any] | None = None,
    bus: RuntimeEventBus | None = None,
) -> None:
    """Publish a :class:`GoalStateChanged` event to the bound (or explicit) bus.

    Silently no-ops when no bus is available — this keeps tests simple
    and avoids cascading failures during early bootstrap.  When the
    caller does not know the session key (e.g. inside a unit test) we
    fall back to a stable ``"<channel>:<chat_id>"`` identifier so the
    subscriber still has enough context to attribute the event.
    """
    target = bus or _active_bus
    if target is None:
        return
    try:
        key = session_key or f"{channel}:{chat_id}"
        ctx = RuntimeEventContext(
            channel=channel,
            chat_id=chat_id,
            session_key=key,
            metadata={},
        )
        event = GoalStateChanged(
            context=ctx,
            session_metadata=dict(session_metadata or {}),
        )
        target.publish_nowait(event)
    except (RuntimeError, ValueError) as exc:
        # Restrict to the exception types the bus may raise under load
        # (full queue, missing subscription) or on schema mismatch
        # (ValueError).  Programmer errors (TypeError, KeyError,
        # AttributeError) are intentionally *not* caught so they
        # surface during tests instead of disappearing in production.
        logger.warning("Failed to publish GoalStateChanged: {}", exc)