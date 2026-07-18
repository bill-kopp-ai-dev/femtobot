"""femtobot_timer tool: timezone-aware time queries.

Migrated from femtobot/agent/tools/time.py. Uses PydanticAI's
Tool constructor — the function signature and Google-style docstring
provide the schema (PydanticAI uses griffe internally).

This is the Phase 1 pilot. It coexists with the legacy
``FemtobotTimerTool`` class; Phase 3 flips the registration to this
new toolset and deletes the legacy class.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic_ai import RunContext, Tool

if TYPE_CHECKING:
    from femtobot.agent.deps import FemtobotDeps


def _resolve_tz(tz_name: str) -> tuple[ZoneInfo | timezone, str | None]:
    """Return ``(tzinfo, fallback_name)``.

    ``fallback_name`` is set when the requested IANA name was
    invalid so the caller can surface a warning.
    """
    try:
        return ZoneInfo(tz_name), None
    except (ZoneInfoNotFoundError, ValueError):
        try:
            return ZoneInfo("UTC"), tz_name or "<empty>"
        except ZoneInfoNotFoundError:
            return timezone.utc, tz_name or "<empty>"


def _impl(query: str, deps: "FemtobotDeps") -> str:
    """Pure implementation — easy to unit-test in isolation."""
    tz_name = (
        getattr(deps.config.agents.defaults, "timezone", None) or "UTC"
    )
    user_tz, fallback = _resolve_tz(tz_name)

    now_user = datetime.now(user_tz)
    now_utc = datetime.now(timezone.utc)

    q = (query or "now").strip().lower()
    if q == "now":
        return f"User-local: {now_user.isoformat()}\nUTC: {now_utc.isoformat()}"
    if q == "utc":
        return now_utc.isoformat()
    if q == "user_local":
        return now_user.isoformat()
    if q == "calendar":
        dst = now_user.utcoffset() is not None and now_user.dst() is not None
        base = (
            f"Timezone: {tz_name}\n"
            f"DST active: {dst}\n"
            f"User-local: {now_user.isoformat()}\n"
            f"UTC: {now_utc.isoformat()}\n"
            f"Week: {now_user.isocalendar().week}\n"
            f"Weekday: {now_user.strftime('%A')}"
        )
        if fallback is not None:
            base += f"\n  Warning: timezone {fallback!r} invalid; using UTC"
        return base
    # Treat query as a date string
    try:
        target = datetime.fromisoformat(query)
        return f"{query} was a {target.strftime('%A')} (week {target.isocalendar().week})."
    except ValueError:
        return (
            f"Unrecognized query {query!r}. Use 'now', 'utc', 'user_local', "
            "'calendar', or an ISO-8601 date."
        )


async def femtobot_timer(
    ctx: RunContext,
    query: str = "now",
) -> str:
    """Return the current time in the user's timezone.

    Args:
        query: One of ``"now"``, ``"utc"``, ``"user_local"``,
            ``"calendar"``, or an ISO-8601 date string for which to
            return the day-of-week and week-of-year.

    Returns:
        A human-readable time string. For ``"calendar"`` returns a
        multi-line block with timezone, DST status, and week info.
    """
    return _impl(query, ctx.deps)


def toolset() -> list[Tool]:
    """Return the toolset containing femtobot_timer."""
    return [Tool(femtobot_timer, takes_ctx=True)]


__all__ = ["femtobot_timer", "toolset"]
