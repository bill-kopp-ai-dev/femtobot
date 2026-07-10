"""FemtobotTimerTool regression tests (v0.1.6).

Pins the runtime behavior of :mod:`femtobot.agent.tools.time`
against the parity baseline established in
``docs/nano_timer_implementation_plan.md``.  Each test names the
property it guards.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from femtobot.agent.tools.context import RequestContext
from femtobot.agent.tools.time import (
    FemtobotTimerTool,
    TimerToolConfig,
    _format_offset,
    _resolve_server_tz,
)

# ---------------------------------------------------------------------------
# Tool metadata
# ---------------------------------------------------------------------------


def test_tool_name_is_femtobot_timer() -> None:
    """The public tool name is ``femtobot_timer`` (v0.1.6 rebrand)."""
    tool = FemtobotTimerTool()
    assert tool.name == "femtobot_timer"


def test_tool_description_mentions_time_and_calendar() -> None:
    """The description advertises time + calendar use cases."""
    desc = FemtobotTimerTool().description
    assert "time" in desc.lower()
    assert "calendar" in desc.lower()
    assert "timezone" in desc.lower()


def test_tool_config_key_is_timer() -> None:
    """The runtime config slot is ``tools.timer``."""
    assert FemtobotTimerTool.config_key == "timer"


def test_tool_exposes_timer_tool_config() -> None:
    """``config_cls()`` returns :class:`TimerToolConfig`."""
    assert FemtobotTimerTool.config_cls() is TimerToolConfig


# ---------------------------------------------------------------------------
# Configuration glue
# ---------------------------------------------------------------------------


def test_enabled_reads_from_config() -> None:
    """``enabled()`` consults ``ctx.config.timer.enable``."""
    ctx = MagicMock()
    ctx.config.timer.enable = False
    assert FemtobotTimerTool.enabled(ctx) is False

    ctx.config.timer.enable = True
    assert FemtobotTimerTool.enabled(ctx) is True


def test_create_uses_workspace_override_when_set() -> None:
    """``create()`` prefers ``timezone_override`` over ``ctx.timezone``."""
    ctx = MagicMock()
    ctx.config.timer.timezone_override = "America/Sao_Paulo"
    ctx.timezone = "UTC"
    tool = FemtobotTimerTool.create(ctx)
    assert tool._timezone == "America/Sao_Paulo"


def test_create_falls_back_to_ctx_timezone() -> None:
    """``create()`` falls back to ``ctx.timezone`` when no override."""
    ctx = MagicMock()
    ctx.config.timer.timezone_override = None
    ctx.timezone = "Europe/Berlin"
    tool = FemtobotTimerTool.create(ctx)
    assert tool._timezone == "Europe/Berlin"


def test_timer_tool_config_defaults() -> None:
    """Default config enables the tool with no timezone override."""
    cfg = TimerToolConfig()
    assert cfg.enable is True
    assert cfg.timezone_override is None


# ---------------------------------------------------------------------------
# ContextAware hook
# ---------------------------------------------------------------------------


def test_set_context_records_channel_and_chat_id() -> None:
    """``set_context`` records channel + chat_id for observability."""
    tool = FemtobotTimerTool()
    ctx = RequestContext(channel="cli", chat_id="abc123")
    tool.set_context(ctx)
    assert tool._channel == "cli"
    assert tool._chat_id == "abc123"


# ---------------------------------------------------------------------------
# _format_offset helper
# ---------------------------------------------------------------------------


def test_format_offset_whole_hour_compact() -> None:
    """A whole-hour offset stays compact: ``UTC-3``, not ``UTC-3:00``."""
    from datetime import timedelta

    assert _format_offset(timedelta(hours=-3)) == "UTC-3"
    assert _format_offset(timedelta(hours=5)) == "UTC+5"
    assert _format_offset(timedelta(hours=0)) == "UTC+0"


def test_format_offset_partial_hour_includes_minutes() -> None:
    """Partial-hour offsets include minutes: India UTC+5:30, Nepal UTC+5:45."""
    from datetime import timedelta

    assert _format_offset(timedelta(hours=5, minutes=30)) == "UTC+5:30"
    assert _format_offset(timedelta(hours=5, minutes=45)) == "UTC+5:45"
    assert _format_offset(timedelta(hours=12, minutes=45)) == "UTC+12:45"
    assert _format_offset(timedelta(hours=-3, minutes=-30)) == "UTC-3:30"


def test_format_offset_none_returns_zero() -> None:
    """A ``None`` offset returns ``"UTC+0"`` instead of raising."""
    assert _format_offset(None) == "UTC+0"


# ---------------------------------------------------------------------------
# _resolve_server_tz helper
# ---------------------------------------------------------------------------


def test_resolve_server_tz_returns_label_and_offset() -> None:
    """The server-tz helper returns ``(label, offset_str)`` as a 2-tuple."""
    label, offset = _resolve_server_tz()
    assert isinstance(label, str)
    assert isinstance(offset, str)
    assert offset.startswith("UTC")


# ---------------------------------------------------------------------------
# execute() — happy paths
# ---------------------------------------------------------------------------


def test_execute_returns_utc_and_user_local_time() -> None:
    """``info_type="time"`` includes UTC and User Local sections."""
    asyncio.run(_collect(FemtobotTimerTool(timezone="UTC"), "time"))
    # We assert this separately below because the helper unwraps.

    async def main():
        tool = FemtobotTimerTool(timezone="UTC")
        result = await tool.execute(info_type="time")
        # Both sections present.
        assert "**UTC Time**" in result
        assert "**User Local Time**" in result
        # Calendar/context sections are NOT included in time mode.
        assert "**Calendar**" not in result
        assert "**Context**" not in result

    asyncio.run(main())


def test_execute_info_type_all_includes_all_sections() -> None:
    """``info_type="all"`` includes time + calendar + context."""
    async def main():
        tool = FemtobotTimerTool(timezone="UTC")
        result = await tool.execute(info_type="all")
        assert "**UTC Time**" in result
        assert "**User Local Time**" in result
        assert "**Calendar**" in result
        assert "**Context**" in result

    asyncio.run(main())


def test_execute_info_type_calendar_includes_weekday() -> None:
    """``info_type="calendar"`` includes weekday, week-of-year, day-of-year."""
    async def main():
        tool = FemtobotTimerTool(timezone="UTC")
        result = await tool.execute(info_type="calendar")
        assert "**Calendar**" in result
        assert "Weekday:" in result
        assert "Week of year:" in result
        assert "Day of year:" in result

    asyncio.run(main())


def test_execute_info_type_timezone_includes_offset_str() -> None:
    """``info_type="timezone"`` includes the offset string under Context."""
    async def main():
        tool = FemtobotTimerTool(timezone="Asia/Tokyo")
        result = await tool.execute(info_type="timezone")
        assert "**Context**" in result
        # Tokyo is UTC+9:00 (no DST), so the offset difference
        # reflects that.
        assert "+9h" in result

    asyncio.run(main())


# ---------------------------------------------------------------------------
# execute() — fallback paths
# ---------------------------------------------------------------------------


def test_execute_invalid_timezone_falls_back_to_utc() -> None:
    """An unknown IANA timezone falls back to UTC and the fallback is named."""
    async def main():
        tool = FemtobotTimerTool(timezone="Mars/Olympus_Mons")
        result = await tool.execute(info_type="all")
        # Fallback footer mentions the bad input verbatim.
        assert "Mars/Olympus_Mons" in result
        assert "using UTC" in result

    asyncio.run(main())


def test_execute_empty_timezone_falls_back_to_utc() -> None:
    """An empty-string timezone also falls back (the empty is named)."""
    async def main():
        tool = FemtobotTimerTool(timezone="")
        result = await tool.execute(info_type="all")
        # The placeholder for empty-string input is "<empty>".
        assert "<empty>" in result
        assert "using UTC" in result

    asyncio.run(main())


def test_execute_unknown_info_type_defaults_to_all() -> None:
    """An unknown ``info_type`` does not crash; it falls back to ``all``."""
    async def main():
        tool = FemtobotTimerTool(timezone="UTC")
        result = await tool.execute(info_type="bogus")
        # All sections present, indicating default-to-all.
        assert "**UTC Time**" in result
        assert "**Calendar**" in result
        assert "**Context**" in result

    asyncio.run(main())


def test_execute_none_info_type_defaults_to_all() -> None:
    """``info_type=None`` also defaults to all (nullable param honored)."""
    async def main():
        tool = FemtobotTimerTool(timezone="UTC")
        result = await tool.execute(info_type=None)
        assert "**UTC Time**" in result
        assert "**Calendar**" in result
        assert "**Context**" in result

    asyncio.run(main())


# ---------------------------------------------------------------------------
# DST handling sanity check (informational, no assertion on date)
# ---------------------------------------------------------------------------


def test_execute_tokyo_offset_is_utc_plus_9() -> None:
    """Tokyo is UTC+9 (no DST) — the offset str must reflect that."""
    async def main():
        tool = FemtobotTimerTool(timezone="Asia/Tokyo")
        result = await tool.execute(info_type="time")
        assert "UTC+9" in result

    asyncio.run(main())


# ---------------------------------------------------------------------------
# Auto-discovery smoke test
# ---------------------------------------------------------------------------


def test_femtobot_timer_tool_is_discovered_by_tool_loader() -> None:
    """ToolLoader's auto-discovery includes the new ``time`` module."""
    from femtobot.agent.tools.loader import ToolLoader
    discovered = ToolLoader().discover()
    # Each class has ``name`` as a property, so we instantiate.
    names = set()
    for cls in discovered:
        try:
            instance = cls()
        except Exception:
            continue
        try:
            names.add(instance.name)
        except Exception:
            continue
    assert "femtobot_timer" in names


def test_femtobot_timer_tool_appears_in_parameters_schema() -> None:
    """Tool.parameters returns a JSON Schema with the expected field."""
    tool = FemtobotTimerTool(timezone="UTC")
    schema = tool.parameters
    if callable(schema):
        schema = schema()
    assert isinstance(schema, dict)
    assert schema.get("type") == "object"
    props = schema.get("properties", {})
    assert "info_type" in props
    info = props["info_type"]
    assert set(info.get("enum", [])) == {
        "time", "timezone", "location", "calendar", "all",
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _collect(tool: FemtobotTimerTool, info_type: str) -> str:
    """Tiny helper that returns the execute() result (kept for future use)."""
    return await tool.execute(info_type=info_type)
