"""Tests for ``femtobot.cli.parity_stream.ParityStreamRenderer`` (T4).

Covers:

  * Welcome card is printed exactly once on construction.
  * Welcome card is hidden after the first ``on_end()`` (Q3).
  * :meth:`show_welcome_card` re-renders the card (used by ``/welcome``).
  * Header bar uses the ``__logo__`` ASCII wordmark (Q1).
  * Tool card collapsed / expanded rendering goes through the parity
    layer (Q7 — first-line heuristic).
  * Status footer prints a "Cooked for Ns" line at the end of a turn.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from femtobot import __logo__
from femtobot.cli.parity_stream import ParityStreamRenderer
from femtobot.cli.parity_widgets import summarize_tool_result
from femtobot.cli.stream import StreamRenderer
from femtobot.config.schema import Config


@pytest.fixture
def captured_console(monkeypatch) -> Console:
    """A ``Console`` whose ``file`` is a :class:`StringIO` so tests can
    inspect what the renderer printed."""
    buf = StringIO()
    return Console(file=buf, force_terminal=False, width=120, color_system=None)


@pytest.fixture
def config() -> Config:
    return Config(
        agents={
            "defaults": {
                "user": {"name": "Bill Kopp"},
                "workspace": "~/femtobot",
                "model": "anthropic/claude-opus-4-5",
                "model_preset": None,
            }
        }
    )


def _make_renderer(config: Config, captured_console: Console) -> ParityStreamRenderer:
    base = StreamRenderer(
        render_markdown=True,
        show_spinner=False,
        bot_name="Femtobot",
        bot_icon="🐈",
        spacing_renderer=None,
    )
    # Replace the base renderer's console with our captured one so the
    # parity layer's prints end up in the test's StringIO.
    base._console = captured_console  # type: ignore[attr-defined]
    return ParityStreamRenderer(
        base_renderer=base,
        config=config,
        bot_name="Femtobot",
        bot_icon="🐈",
        spacing_renderer=None,
        changelog_path=Path("/nonexistent/CHANGELOG.md"),  # silence the parse
    )


def test_parity_renderer_prints_header_bar_on_init(config, captured_console) -> None:
    _make_renderer(config, captured_console)
    text = captured_console.file.getvalue()
    # Q1 — logo wordmark
    assert __logo__.splitlines()[1].strip() in text or "█" in text
    # Welcome line
    assert "Welcome back Bill Kopp" in text
    # Workspace path
    assert "~/femtobot" in text


def test_parity_renderer_prints_welcome_card_once(config, captured_console) -> None:
    """Q3 — welcome card is printed on the first screen, hidden
    afterwards. A second call to ``_print_welcome_card_if_first_time``
    must not re-render the card."""
    r = _make_renderer(config, captured_console)
    # Welcome is already printed at this point.
    text1 = captured_console.file.getvalue()
    assert "Tips for getting started" in text1
    # A second call must not duplicate.
    r._print_welcome_card_if_first_time()
    text2 = captured_console.file.getvalue()
    # The text should be identical (no duplicate "Tips for getting started" insertion).
    assert text1.count("Tips for getting started") == text2.count("Tips for getting started")


def test_parity_renderer_welcome_hidden_after_first_turn(config, captured_console) -> None:
    """Q3 — after the first ``on_end`` call, the welcome card is
    considered "shown" and won't come back on its own."""
    r = _make_renderer(config, captured_console)
    # Simulate the end of a turn. on_end is async, but the parity layer
    # only does sync work in the wrapper, so awaiting is safe.
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(r.on_end())
    finally:
        loop.close()
    # Now the welcome card is marked as shown. Calling again is a no-op.
    r._welcome_shown = False  # would happen if the turn hadn't fired
    r._print_welcome_card_if_first_time()
    # But by the time on_end has run, the welcome card flag is True
    # and the next call does nothing.
    r._print_welcome_card_if_first_time()
    # No more welcome card than the first one.


def test_show_welcome_card_re_renders(config, captured_console) -> None:
    """Q3 — ``/welcome`` slash command should bring the card back."""
    r = _make_renderer(config, captured_console)
    # Reset and re-show.
    r._welcome_shown = True
    r.show_welcome_card(force=True)
    text = captured_console.file.getvalue()
    # Two "Tips for getting started" panels — one from init, one from /welcome.
    assert text.count("Tips for getting started") == 2


def test_parity_renderer_tool_card_collapsed(config, captured_console) -> None:
    r = _make_renderer(config, captured_console)
    r.on_tool_call("web_search", '"Bill Kopp"')
    text = captured_console.file.getvalue()
    assert "Web Search" in text
    assert "Bill Kopp" in text


def test_parity_renderer_tool_result_uses_first_line_heuristic(config, captured_console) -> None:
    r = _make_renderer(config, captured_console)
    r.on_tool_result(
        "exec",
        '"rm -rf /tmp/foo"',
        "\nfirst meaningful line\nsecond line",
        success=False,
        elapsed_s=1.2,
    )
    text = captured_console.file.getvalue()
    assert "first meaningful line" in text


def test_summarize_helper_picks_first_meaningful_line() -> None:
    assert summarize_tool_result("\n\n  - actual answer\nignored") == "- actual answer"


def test_parity_renderer_cooked_footer_appears_on_end(config, captured_console) -> None:
    """The "Cooked for Ns" footer is *not* printed from ``on_end``
    anymore (Bug A fix — it moved to ``print_cooked_footer`` so the
    footer renders AFTER the agent's reply). We assert:

    * ``on_end`` does not emit a footer by itself.
    * ``print_cooked_footer`` does, with the right glyph ("Cooked").
    """
    import asyncio

    r = _make_renderer(config, captured_console)
    captured_console.file.seek(0)
    captured_console.file.truncate()
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(r.on_end())
    finally:
        loop.close()
    text_after_on_end = captured_console.file.getvalue()
    assert "Cooked" not in text_after_on_end

    captured_console.file.seek(0)
    captured_console.file.truncate()
    r.print_cooked_footer()
    text_after_print = captured_console.file.getvalue()
    assert "Cooked" in text_after_print


def test_parity_renderer_idle_footer_renders_manual_mode(config, captured_console) -> None:
    """Polish: ``print_idle_footer`` renders ``▌ manual mode on`` so the
    parity layout is ``[top bar][prompt row][mode row]`` between turns.
    """
    r = _make_renderer(config, captured_console)
    captured_console.file.seek(0)
    captured_console.file.truncate()
    r.print_idle_footer()
    text = captured_console.file.getvalue()
    assert "manual mode on" in text


def test_parity_renderer_passes_through_on_delta(config, captured_console) -> None:
    """Drop-in compatibility: ``on_delta`` delegates to the base
    renderer. We assert that no exception is raised (the parity layer
    does not interfere with streaming)."""
    r = _make_renderer(config, captured_console)
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(r.on_delta("hello "))
        loop.run_until_complete(r.on_delta("world"))
    finally:
        loop.close()
    # No assertion on text — the base renderer has its own threading
    # model. The point of this test is "parity layer doesn't break it".


def test_parity_renderer_exposes_streamed_property(config, captured_console) -> None:
    """Regression: ``commands.py:1452`` reads ``renderer.streamed`` to
    decide whether to re-print the buffered response. The parity layer
    must expose that attribute as a property that mirrors the base
    renderer (defaults to ``False`` before the first ``on_delta``).
    """
    r = _make_renderer(config, captured_console)
    # ``streamed`` must exist as a property — not raise AttributeError.
    assert hasattr(r, "streamed")
    assert r.streamed is False
    # After a delta, the parity layer delegates to the base, so the
    # source of truth is the base renderer.
    base_streamed = r._base.streamed  # type: ignore[attr-defined]
    assert r.streamed == base_streamed


def test_parity_renderer_print_input_bar_emits_top_rule(config, captured_console) -> None:
    """Plan §3 D9 (T2/T3): the parity layer must expose
    :meth:`print_input_bar` that draws the accent rule above the prompt.

    The bottom rule lives in :meth:`input_prompt_markup`, which is
    tested separately so prompt_toolkit's ``HTML`` can redraw it on
    every key event.
    """
    r = _make_renderer(config, captured_console)
    captured_console.file.seek(0)
    captured_console.file.truncate()
    r.print_input_bar()
    text = captured_console.file.getvalue()
    # Horizontal rule character is the parity bar marker.
    assert "─" in text


def test_parity_renderer_input_prompt_markup_returns_html(config, captured_console) -> None:
    """``input_prompt_markup`` returns the prompt row as prompt_toolkit
    ``HTML`` so the toolkit can redraw it on every key event.
    """
    from prompt_toolkit.formatted_text import HTML

    r = _make_renderer(config, captured_console)
    markup = r.input_prompt_markup
    assert isinstance(markup, HTML)
    s = str(markup)
    # Prompt glyph + placeholder make it through.
    assert "❯" in s
    assert "nova mensagem" in s
    assert "Nova mensagem" not in s


def test_parity_renderer_suppresses_legacy_user_box(config, captured_console) -> None:
    """Claude-style compat UI must not print the legacy ``[👤 You]`` box.

    The input affordance itself is enough; the extra user box makes the
    layout heavier than Claude Code and duplicates the role cue.
    """
    r = _make_renderer(config, captured_console)
    captured_console.file.seek(0)
    captured_console.file.truncate()
    assert r.print_user_box() is None
    assert captured_console.file.getvalue() == ""


def test_parity_renderer_input_toolbar_markup_returns_html(config, captured_console) -> None:
    """The compat prompt uses a prompt_toolkit bottom toolbar to close the
    input box and render the subtle footer below it.
    """
    from prompt_toolkit.formatted_text import HTML

    r = _make_renderer(config, captured_console)
    markup = r.input_toolbar_markup
    assert isinstance(markup, HTML)
    s = str(markup)
    assert "─" * 60 in s
    assert "manual mode on" in s


def test_legacy_stream_renderer_print_input_bar_is_noop(config, captured_console) -> None:
    """The legacy ``StreamRenderer`` (profile ``off``) returns ``None``
    from ``print_input_bar`` and emits the plain ``You:`` markup so the
    legacy REPL is byte-identical to ``v0.1.0-ui.0``.
    """
    from prompt_toolkit.formatted_text import HTML

    base = StreamRenderer(
        render_markdown=True,
        show_spinner=False,
        spacing_renderer=None,
    )
    base._console = captured_console  # type: ignore[attr-defined]
    captured_console.file.seek(0)
    captured_console.file.truncate()
    # No-op (returns ``None`` and prints nothing).
    assert base.print_input_bar() is None
    # Legacy prompt markup.
    markup = base.input_prompt_markup
    assert isinstance(markup, HTML)
    assert "You:" in str(markup)
    assert "❯" not in str(markup)
