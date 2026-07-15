"""Tests for the v0.1.0-ui.0+ UI-parity slash commands (T8).

Covers:

  * ``/ui`` with no args lists the current profile.
  * ``/ui compat`` mutates the per-session ``ui_parity.profile`` (Q10).
  * ``/ui full`` mutates and emits the "arrives in RC" notice.
  * ``/welcome`` returns a welcome card (works in both parity + legacy).
  * ``/release-notes`` parses the CHANGELOG.md and shows the top entry.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from femtobot.bus.events import InboundMessage, OutboundMessage
from femtobot.command.builtin import cmd_release_notes, cmd_ui, cmd_welcome
from femtobot.command.router import CommandContext
from femtobot.config.schema import Config


@pytest.fixture
def loop_with_config() -> SimpleNamespace:
    cfg = Config(agents={"defaults": {"user": {"name": "Bill"}}})
    return SimpleNamespace(_config=cfg)


def _make_ctx(loop, args: str = "") -> CommandContext:
    msg = InboundMessage(
        channel="cli", chat_id="chat", sender_id="user", content="/ui"
    )
    return CommandContext(
        msg=msg, session=None, key="chat", raw="/ui", args=args, loop=loop
    )


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# /ui
# ---------------------------------------------------------------------------


def test_ui_no_args_lists_current_profile(loop_with_config) -> None:
    out = _run(cmd_ui(_make_ctx(loop_with_config, args="")))
    assert isinstance(out, OutboundMessage)
    assert "off" in out.content
    assert "compat" in out.content
    assert "full" in out.content


def test_ui_compat_switches_per_session(loop_with_config) -> None:
    out = _run(cmd_ui(_make_ctx(loop_with_config, args="compat")))
    assert "compat" in out.content
    # Per-session mutation, Q10: the in-memory config changes, but the
    # user did NOT write to config.json.
    assert loop_with_config._config.agents.defaults.cli.ui_parity.profile == "compat"


def test_ui_off_switches_per_session(loop_with_config) -> None:
    # Start in compat, then /ui off
    loop_with_config._config.agents.defaults.cli.ui_parity.profile = "compat"
    out = _run(cmd_ui(_make_ctx(loop_with_config, args="off")))
    assert "off" in out.content
    assert loop_with_config._config.agents.defaults.cli.ui_parity.profile == "off"


def test_ui_full_emits_preview_notice(loop_with_config) -> None:
    out = _run(cmd_ui(_make_ctx(loop_with_config, args="full")))
    assert "full" in out.content
    assert "RC" in out.content or "preview" in out.content


def test_ui_rejects_unknown_profile(loop_with_config) -> None:
    out = _run(cmd_ui(_make_ctx(loop_with_config, args="mystery")))
    assert "Unknown profile" in out.content


# ---------------------------------------------------------------------------
# /welcome
# ---------------------------------------------------------------------------


def test_welcome_returns_a_welcome_card(loop_with_config) -> None:
    out = _run(cmd_welcome(_make_ctx(loop_with_config, args="")))
    # The legacy fallback path emits a static panel with the tips.
    assert "Tips for getting started" in out.content or "Welcome card re-rendered" in out.content


def test_welcome_uses_active_renderer_when_available() -> None:
    class _StubRenderer:
        called_with: object = None

        def show_welcome_card(self, *, force: bool = False) -> None:
            self.called_with = force

    renderer = _StubRenderer()
    # Inject via the global hook the command consults.
    import femtobot.command.builtin as builtin_mod
    builtin_mod._ui_active_renderer = renderer
    try:
        out = _run(cmd_welcome(_make_ctx(SimpleNamespace(_config=Config()), args="")))
        assert "Welcome card re-rendered" in out.content
        assert renderer.called_with is True
    finally:
        del builtin_mod._ui_active_renderer


# ---------------------------------------------------------------------------
# /release-notes
# ---------------------------------------------------------------------------


def test_release_notes_uses_changelog(tmp_path, monkeypatch) -> None:
    # Patch the parsed path so the test does not depend on the live
    # CHANGELOG.md (which is currently being edited).
    from pathlib import Path
    from femtobot.command import builtin as builtin_mod

    fake = tmp_path / "CHANGELOG.md"
    fake.write_text(
        "# Changelog\n"
        "\n"
        "## [v9.9.9-ui] - 2026-07-15\n"
        "\n"
        "### Added\n"
        "- test bullet one\n"
        "- test bullet two\n",
        encoding="utf-8",
    )
    # Monkeypatch the hard-coded path the command uses.
    import femtobot.cli.parity_widgets as pw

    orig = pw.Path
    pw.Path = lambda *a, **kw: fake if (a and str(a[0]).endswith("CHANGELOG.md")) else orig(*a, **kw)
    try:
        out = _run(cmd_release_notes(_make_ctx(SimpleNamespace(_config=Config()), args="")))
    finally:
        pw.Path = orig
    assert "v9.9.9-ui" in out.content
    assert "test bullet one" in out.content
    assert "test bullet two" in out.content


def test_release_notes_handles_missing_file(tmp_path, monkeypatch) -> None:
    import femtobot.cli.parity_widgets as pw
    from pathlib import Path

    orig = pw.Path
    missing = tmp_path / "no-such-CHANGELOG.md"
    pw.Path = lambda *a, **kw: missing if (a and str(a[0]).endswith("CHANGELOG.md")) else orig(*a, **kw)
    try:
        out = _run(cmd_release_notes(_make_ctx(SimpleNamespace(_config=Config()), args="")))
    finally:
        pw.Path = orig
    assert "Could not parse" in out.content or "missing" in out.content
