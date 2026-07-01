"""Tests for the lightweight status line module."""

from __future__ import annotations

from types import SimpleNamespace

from rich.text import Text

from femtobot.cli.status_line import (
    format_elapsed,
    format_tokens,
    render_session_status_line,
)


def test_format_tokens_with_thousands_separator() -> None:
    assert format_tokens(0) == "0"
    assert format_tokens(1_000) == "1,000"
    assert format_tokens(12_345) == "12,345"


def test_format_elapsed_under_minute() -> None:
    s = format_elapsed(0.0, now=1.234)
    assert s.endswith("s")
    assert s.startswith("1.")


def test_format_elapsed_over_minute() -> None:
    # 75.5s → 1m15.5s
    s = format_elapsed(0.0, now=75.5)
    assert s == "1m15.5s"


def test_format_elapsed_clamps_negative() -> None:
    s = format_elapsed(10.0, now=5.0)
    assert s.endswith("s") and s.startswith("0.")


def test_render_session_status_line_basic() -> None:
    loop = SimpleNamespace(
        model="anthropic/claude-opus-4-5",
        _last_usage={"prompt_tokens": 1234},
        _start_time=0.0,
    )
    out = render_session_status_line(loop, now=2.5)
    assert isinstance(out, Text)
    rendered = out.plain
    assert "anthropic/claude-opus-4-5" in rendered
    assert "1,234 tok in" in rendered


def test_render_session_status_line_no_start_time() -> None:
    """When ``_start_time`` is missing, the elapsed segment is dropped silently."""
    loop = SimpleNamespace(
        model="m", _last_usage={"prompt_tokens": 0}, _start_time=None
    )
    out = render_session_status_line(loop)
    rendered = out.plain
    assert "tok in" not in rendered


def test_render_session_status_line_disabled_sections() -> None:
    loop = SimpleNamespace(
        model="m", _last_usage={"prompt_tokens": 999}, _start_time=0.0
    )
    out = render_session_status_line(loop, now=2.0, show_tokens=False, show_elapsed=False)
    rendered = out.plain
    assert "tok" not in rendered
    assert "s" not in rendered  # no elapsed either
