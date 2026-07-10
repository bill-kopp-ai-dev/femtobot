"""FemtobotTimerTool: time, timezone, and calendar awareness.

Provides accurate time, timezone, and calendar information so the
agent never has to estimate UTC offsets from training data.

Ported from nanobot's ``nano_timer`` (see ``nanobot/agent/tools/time.py``).
Femtobot-specific adaptations:

* Public class is renamed ``FemtobotTimerTool`` and the public tool
  name is ``femtobot_timer`` (the v0.1.6 user-decision was to
  rebrand for project consistency; nanobot compatibility is not a
  goal yet).
* Day-of-week output is English-only — Femtobot has no i18n
  subsystem to mirror the upstream pt/en parallel.
* Per-tool config lives at ``tools.timer`` in
  :class:`ToolsConfig`; an optional ``timezone_override`` lets a
  workspace pin the user's tz without touching
  ``agents.defaults.timezone``.

Implementation notes:

* The two helpers ``_resolve_server_tz`` and ``_format_offset`` are
  verbatim ports of nanobot's — they handle the
  ``TZ=Asia/Tokyo`` POSIX edge case that the original 2026-06-22
  implementation document did not consider.
* The tz-fallback path (``ZoneInfoNotFoundError``) also handles
  the no-tzdb-on-Windows edge case by falling back to
  ``datetime.timezone.utc``.
* ``set_context`` is implemented to keep parity with
  :class:`ContextAware`, even though Femtobot does not yet
  consume the recorded ``channel``/``chat_id``.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger

from femtobot.agent.tools.base import Tool, tool_parameters
from femtobot.agent.tools.context import ContextAware, RequestContext
from femtobot.agent.tools.schema import StringSchema, tool_parameters_schema
from femtobot.config.schema import Base

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class TimerToolConfig(Base):
    """Configuration for the femtobot_timer tool.

    ``enable`` lets a workspace disable the tool without touching
    the rest of the agent loop.
    ``timezone_override`` is an optional per-workspace override of
    the agent timezone for *this tool only*.  When unset we fall
    back to ``ctx.timezone``, which the loop populates from
    ``agents.defaults.timezone``.
    """

    enable: bool = True
    timezone_override: str | None = None


# ---------------------------------------------------------------------------
# Tool parameters schema (OpenAI-compatible JSON Schema fragment)
# ---------------------------------------------------------------------------


_TIMER_PARAMETERS = tool_parameters_schema(
    info_type=StringSchema(
        "What information to return: 'time' | 'timezone' | 'location' | 'calendar' | 'all'.",
        enum=("time", "timezone", "location", "calendar", "all"),
        nullable=True,
    ),
    description=(
        "Selects the section of the time report. Defaults to 'all' when null or unknown."
    ),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_server_tz() -> tuple[str, str]:
    """Return ``(label, offset_str)`` for the server's local timezone.

    Prefers the IANA name (``tzinfo.key``) over ``tzname()`` because the
    latter can return a numeric offset (e.g. ``"-03"``) on platforms
    where the tzdata database is incomplete — common in slim Docker
    images.

    When the runtime is using ``TZ=Asia/Tokyo`` style POSIX timestamps
    (resolved via ``time.tzset()``), ``tzinfo`` is a plain
    ``datetime.timezone`` with no ``.key`` and ``tzname()`` returns
    the short form (``"JST"``, ``"CEST"``).  In that case we still
    report a sensible label: the ``TZ`` env var if it is a valid IANA
    name, else the ``tzname()`` result if it is not a bare offset,
    else a generic ``"server-local"`` wrapper.

    Returns ``(label, offset_str)`` where ``offset_str`` is in the
    form ``UTC+N``, ``UTC-N``, or ``UTC+N:MM`` for partial-hour
    offsets (see :func:`_format_offset`).
    """
    server = datetime.now().astimezone()
    tzinfo = server.tzinfo
    label: str
    if tzinfo is not None:
        key = getattr(tzinfo, "key", None)
        if key:
            label = key
        else:
            name = tzinfo.tzname(server) or "UTC"
            # IANA names contain a slash (e.g. "America/Sao_Paulo");
            # offsets like "-03" or "+0530" do not.
            if "/" in name:
                label = name
            else:
                # ``TZ=Asia/Tokyo`` -> key=None, name="JST".  Try
                # the env var: if it has a slash it is IANA, else
                # fall back to a wrapped short label to avoid
                # losing the signal.
                tz_env = os.environ.get("TZ", "")
                if "/" in tz_env:
                    label = tz_env
                else:
                    label = f"server-local({name})"
    else:
        label = "UTC"
    offset = server.utcoffset()
    if offset is None:
        return label, "UTC+0"
    return label, _format_offset(offset)


def _format_offset(offset: Any) -> str:
    """Format a ``timedelta`` offset as ``UTC[+/-]H[:MM]``.

    Offsets not aligned to whole hours (India UTC+5:30, Nepal
    UTC+5:45, Chatham UTC+12:45) include the minute component.
    Whole-hour offsets stay as ``UTC+N`` to keep the output compact.
    """
    if offset is None:
        return "UTC+0"
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    abs_min = abs(total_minutes)
    hours, minutes = divmod(abs_min, 60)
    if minutes:
        return f"UTC{sign}{hours}:{minutes:02d}"
    return f"UTC{sign}{hours}"


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------


@tool_parameters(_TIMER_PARAMETERS)
class FemtobotTimerTool(Tool, ContextAware):
    """Provide accurate time, timezone, and calendar information.

    Uses IANA timezone with automatic DST handling.  Source of user
    timezone is :class:`ToolContext.timezone`
    (``agent_defaults.timezone``), injected via :meth:`create` — the
    tool never reads config files directly.
    """

    config_key = "timer"

    @classmethod
    def config_cls(cls):
        return TimerToolConfig

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return ctx.config.timer.enable

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        tz_override = getattr(ctx.config.timer, "timezone_override", None)
        return cls(timezone=tz_override or ctx.timezone)

    def __init__(self, timezone: str = "UTC"):
        self._timezone = timezone
        # tz_fallback_name is the bad input string (or None if tz
        # was OK).  Use a separate bool check in _format() because
        # empty-string is falsy.
        self._tz_fallback_name: str | None = None
        self._channel: str = ""
        self._chat_id: str = ""

    def set_context(self, ctx: RequestContext) -> None:
        """Record the current request context for observability/logging."""
        self._channel = ctx.channel
        self._chat_id = ctx.chat_id

    @property
    def name(self) -> str:
        return "femtobot_timer"

    @property
    def description(self) -> str:
        return (
            "Returns accurate time, timezone, and calendar information using "
            "IANA timezone with automatic DST handling. Call this before "
            "scheduling, cron jobs, reminders, or any time-sensitive operation "
            "where wrong time would cause harm. Also useful when the user asks "
            "about current time, date, or timezone, or when converting/comparing "
            "times across zones."
        )

    def _compute_payload(self) -> dict[str, Any]:
        """Build the time report payload from the current instant."""
        now_utc = datetime.now(timezone.utc)
        try:
            user_tz = ZoneInfo(self._timezone)
            self._tz_fallback_name = None
        except (ZoneInfoNotFoundError, ValueError):
            logger.warning(
                "Invalid IANA timezone '{}' in femtobot_timer; falling back to UTC",
                self._timezone,
            )
            # Defensive: even ``ZoneInfo("UTC")`` can raise on a
            # platform with no tzdb and no ``tzdata`` package
            # installed (notably Windows without our pinned
            # runtime dep).  In that case we fall back to the
            # stdlib ``datetime.timezone.utc`` constant, which
            # never depends on the tzdb.
            try:
                user_tz = ZoneInfo("UTC")
            except ZoneInfoNotFoundError:
                logger.error(
                    "zoneinfo database not available on this system; "
                    "femtobot_timer will use the stdlib UTC constant"
                )
                user_tz = timezone.utc
            # Preserve the raw input (even empty string) so the
            # warning footer can name it.  The renderer checks
            # `is not None`, not truthiness.
            self._tz_fallback_name = self._timezone
        user_now = now_utc.astimezone(user_tz)
        server_local = datetime.now().astimezone()
        server_label, server_offset_str = _resolve_server_tz()
        user_offset = user_now.utcoffset()
        same_tz = user_tz == server_local.tzinfo
        diff_from_utc = "N/A"
        if user_offset is not None:
            total_minutes = int(user_offset.total_seconds() // 60)
            sign = "+" if total_minutes >= 0 else "-"
            abs_min = abs(total_minutes)
            hours, minutes = divmod(abs_min, 60)
            if minutes:
                diff_from_utc = f"{sign}{hours}h{minutes:02d}m"
            else:
                diff_from_utc = f"{sign}{hours}h"
        return {
            "utc": {
                "time": now_utc.strftime("%H:%M:%S"),
                "date": now_utc.strftime("%Y-%m-%d"),
                "iso": now_utc.isoformat(),
                "unix": int(now_utc.timestamp()),
            },
            "user": {
                "time": user_now.strftime("%H:%M:%S"),
                "date": user_now.strftime("%Y-%m-%d"),
                # When the configured tz was invalid we fell back
                # to UTC; report "UTC" rather than echoing the
                # bad input back.
                "timezone": "UTC" if self._tz_fallback_name is not None else str(user_tz),
                "offset": _format_offset(user_offset),
            },
            "calendar": {
                "weekday": user_now.strftime("%A"),
                "week_of_year": int(user_now.strftime("%W")),
                "day_of_year": int(user_now.strftime("%j")),
                "weekend": user_now.weekday() >= 5,
            },
            "context": {
                "server_timezone": server_label,
                "server_offset": server_offset_str,
                "same_timezone": same_tz,
                "diff_from_utc_hours": diff_from_utc,
            },
        }

    def _format(self, info_type: str, payload: dict[str, Any]) -> str:
        """Render the payload as a markdown time report."""
        lines: list[str] = []
        if info_type in ("time", "all"):
            utc = payload["utc"]
            user = payload["user"]
            lines.append("**UTC Time**")
            lines.append(f"  Time: {utc['time']}")
            lines.append(f"  Date: {utc['date']}")
            lines.append(f"  ISO: {utc['iso']}")
            lines.append(f"  Unix: {utc['unix']}")
            lines.append("")
            lines.append("**User Local Time**")
            lines.append(f"  Time: {user['time']}")
            lines.append(f"  Date: {user['date']}")
            lines.append(f"  Timezone: {user['timezone']}")
            lines.append(f"  Offset: {user['offset']}")
        if info_type in ("calendar", "all"):
            if lines and lines[-1] != "":
                lines.append("")
            cal = payload["calendar"]
            lines.append("**Calendar**")
            lines.append(f"  Weekday: {cal['weekday']}")
            lines.append(f"  Week of year: {cal['week_of_year']}")
            lines.append(f"  Day of year: {cal['day_of_year']}")
            lines.append(f"  Weekend: {'Yes' if cal['weekend'] else 'No'}")
        if info_type in ("timezone", "location", "all"):
            if lines and lines[-1] != "":
                lines.append("")
            ctx_block = payload["context"]
            lines.append("**Context**")
            lines.append(f"  Server timezone: {ctx_block['server_timezone']}")
            lines.append(f"  Server offset: {ctx_block['server_offset']}")
            lines.append(
                f"  Same timezone as user: "
                f"{'Yes' if ctx_block['same_timezone'] else 'No'}"
            )
            lines.append(
                f"  Difference from UTC: {ctx_block['diff_from_utc_hours']}"
            )
        if self._tz_fallback_name is not None:
            if lines and lines[-1] != "":
                lines.append("")
            # Use a quoted placeholder for the empty-string case so
            # the warning line is still informative (rather than
            # `''`).
            label = self._tz_fallback_name if self._tz_fallback_name else "<empty>"
            lines.append(
                f"  ⚠️ timezone '{label}' invalid; using UTC"
            )
        return "\n".join(lines)

    async def execute(
        self,
        info_type: str | None = "all",
        **kwargs: Any,
    ) -> str:
        """Return a markdown time report for the requested ``info_type``.

        Unknown ``info_type`` values are logged and treated as
        ``"all"``.  Any internal failure is logged and reported
        back to the caller as a markdown error string — the agent
        loop never crashes mid-tool-call.
        """
        try:
            if info_type is None or info_type not in (
                "time", "timezone", "location", "calendar", "all",
            ):
                if info_type is not None and info_type != "all":
                    logger.warning(
                        "femtobot_timer received invalid info_type='{}'; defaulting to 'all'",
                        info_type,
                    )
                info_type = "all"
            payload = self._compute_payload()
            return self._format(info_type, payload)
        except Exception as exc:
            logger.exception("femtobot_timer failed: {}", exc)
            return f"Error getting time information: {type(exc).__name__}: {exc}"
