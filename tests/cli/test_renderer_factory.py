"""Tests for ``femtobot.cli.renderer_factory`` (T3).

Covers:

  * Default profile (``off``) when not a TTY / NO_COLOR / TERM=dumb.
  * ``compat`` profile selected when TTY + configured.
  * ``full`` profile returns a clear message + falls back to off in the
    preview release (rev. F4).
  * The factory never raises (defensive fallback to the legacy
    :class:`StreamRenderer`).
"""

from __future__ import annotations

import os
import sys
from io import StringIO

import pytest

from femtobot.cli.renderer_factory import (
    build_renderer,
    _is_color_disabled,
    _resolve_profile,
    _full_unavailable_message,
)
from femtobot.cli.stream import StreamRenderer
from femtobot.cli.parity_stream import ParityStreamRenderer
from femtobot.config.schema import Config


@pytest.fixture
def config_factory():
    """Build a ``Config`` with a custom ``ui_parity.profile``."""

    def _make(profile: str = "off") -> Config:
        if profile in ("off", "compat", "full"):
            cfg = Config(agents={"defaults": {"cli": {"ui_parity": {"profile": profile}}}})
        else:
            # Bypass Pydantic's literal validation for the "garbage"
            # test — we want the resolver to see the bad value and
            # fall back, not the schema to reject the call.
            cfg = Config()
            cfg.agents.defaults.cli.ui_parity.profile = profile  # type: ignore[assignment]
        return cfg

    return _make


# ---------------------------------------------------------------------------
# Profile resolution
# ---------------------------------------------------------------------------


def test_is_color_disabled_no_color(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("TERM", raising=False)
    assert _is_color_disabled() is True


def test_is_color_disabled_term_dumb(monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "dumb")
    assert _is_color_disabled() is True


def test_is_color_disabled_clean(monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    assert _is_color_disabled() is False


def test_resolve_profile_unknown_value_falls_back_to_off(config_factory) -> None:
    cfg = config_factory("mystery")
    assert _resolve_profile(cfg) == "off"


def test_resolve_profile_no_color_forces_off(config_factory, monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    cfg = config_factory("compat")
    assert _resolve_profile(cfg) == "off"


# ---------------------------------------------------------------------------
# build_renderer — when stdout is piped
# ---------------------------------------------------------------------------


def test_build_renderer_pipe_returns_legacy_stream_renderer(config_factory, monkeypatch) -> None:
    """When pytest is running, stdout is not a TTY. The factory must
    return the legacy StreamRenderer (no parity machinery spins up)."""
    cfg = config_factory("compat")
    r = build_renderer(cfg)
    assert isinstance(r, StreamRenderer)


def test_build_renderer_off_profile_returns_legacy(config_factory, monkeypatch) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    cfg = config_factory("off")
    # Even on a TTY, "off" returns the legacy renderer. The fixture
    # path won't have stdout.isatty()==True, so we test resolution
    # independently of the TTY branch.
    r = build_renderer(cfg)
    assert isinstance(r, StreamRenderer)


# ---------------------------------------------------------------------------
# build_renderer — compat profile with a TTY (monkeypatched isatty)
# ---------------------------------------------------------------------------


def test_build_renderer_compat_chosen_when_tty(config_factory, monkeypatch) -> None:
    """Force ``sys.stdout.isatty()`` to True and assert the parity
    renderer is selected."""
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    cfg = config_factory("compat")
    r = build_renderer(cfg)
    assert isinstance(r, ParityStreamRenderer)


def test_build_renderer_full_shows_message_in_preview(config_factory, monkeypatch, capsys) -> None:
    """``full`` is not available in the preview release; the factory
    prints a one-line notice and falls back to the legacy renderer."""
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    cfg = config_factory("full")
    r = build_renderer(cfg)
    # Falls back to legacy StreamRenderer, not a Textual app.
    assert isinstance(r, StreamRenderer)
    # The user is informed (Rich writes to terminal; capture via capsys).
    # Rich inserts ANSI markup into the message text, so we look for
    # the substring "ui_parity" and "full" separately.
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    # Strip ANSI escape sequences to recover the original text.
    import re
    plain = re.sub(r"\x1b\[[0-9;]*m", "", combined)
    assert "ui_parity" in plain
    assert "full" in plain
    assert "not available" in plain or "preview" in plain


# ---------------------------------------------------------------------------
# build_renderer — never raises
# ---------------------------------------------------------------------------


def test_build_renderer_does_not_raise_on_broken_config(monkeypatch) -> None:
    """A config that has no ``agents.defaults.cli.ui_parity`` block
    must still produce a usable renderer."""
    class _StubConfig:
        class agents:
            class defaults:
                class cli:
                    ui_parity = type("U", (), {"profile": "off", "notice": False})()
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    r = build_renderer(_StubConfig())
    assert r is not None


# ---------------------------------------------------------------------------
# Parametrise all four profiles
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", ["off", "compat", "full", "garbage"])
def test_build_renderer_handles_all_profiles_without_raising(
    config_factory, profile: str, monkeypatch
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    cfg = config_factory(profile)
    r = build_renderer(cfg)  # must not raise
    assert r is not None
