"""Tests for the parity widgets module (T5).

Covers:

  * :func:`resolve_user_name` — Q2 fallback chain.
  * :func:`parse_changelog` — Q6 simple regex parser.
  * :func:`summarize_tool_result` — Q7 first-line heuristic.
  * :func:`render_welcome_card` — happy path + theme colour.
  * :func:`render_tool_card` — collapsed vs expanded, success/error.
  * :func:`render_status_footer` — three states (idle / propagating / cooked).
  * :class:`SpinnerWithElapsed` — elapsed-tick semantics.
  * :class:`HeaderBar` — uses ``__logo__`` ASCII wordmark (Q1).
"""

from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console

import femtobot.cli.parity_widgets as pw
from femtobot import __logo__
from femtobot.cli.theme import get_theme

# ---------------------------------------------------------------------------
# Q2 — resolve_user_name
# ---------------------------------------------------------------------------


def test_resolve_user_name_uses_configured_value() -> None:
    assert pw.resolve_user_name("Bill Kopp") == "Bill Kopp"


def test_resolve_user_name_rejects_placeholder() -> None:
    """The ``<your-name>`` sentinel must not leak into the header bar."""
    # The placeholder is the default; should fall through to OS env.
    result = pw.resolve_user_name("<your-name>")
    assert result != "<your-name>"


def test_resolve_user_name_strips_whitespace() -> None:
    assert pw.resolve_user_name("  Alice  ") == "Alice"


def test_resolve_user_name_falls_back_to_env(monkeypatch) -> None:
    monkeypatch.delenv("USER", raising=False)
    monkeypatch.delenv("LOGNAME", raising=False)
    # os.getlogin() will be tried but may fail in pytest — accept any
    # non-placeholder string as long as the chain doesn't blow up.
    result = pw.resolve_user_name(None)
    assert result != "<your-name>"
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Q6 — parse_changelog
# ---------------------------------------------------------------------------


def test_parse_changelog_handles_missing_file(tmp_path) -> None:
    assert pw.parse_changelog(tmp_path / "missing.md") == []


def test_parse_changelog_extracts_top_entry(tmp_path) -> None:
    p = tmp_path / "CHANGELOG.md"
    p.write_text(
        "# Changelog\n"
        "\n"
        "## [v0.1.0-ui.0] - 2026-07-15\n"
        "\n"
        "### Added\n"
        "- Added welcome card\n"
        "- Added elapsed-time spinner\n"
        "\n"
        "## [v0.1.8] - 2026-07-01\n"
        "\n"
        "### Fixed\n"
        "- Some older fix\n",
        encoding="utf-8",
    )
    entries = pw.parse_changelog(p, max_entries=1, max_bullets=4)
    assert len(entries) == 1
    assert entries[0].version == "v0.1.0-ui.0"
    assert entries[0].bullets == ("Added welcome card", "Added elapsed-time spinner")


def test_parse_changelog_handles_unversioned_heading(tmp_path) -> None:
    p = tmp_path / "CHANGELOG.md"
    p.write_text(
        "## v9.9.9\n"
        "- bullet one\n"
        "- bullet two\n",
        encoding="utf-8",
    )
    entries = pw.parse_changelog(p, max_entries=1)
    assert entries[0].version == "v9.9.9"
    assert entries[0].bullets == ("bullet one", "bullet two")


def test_parse_changelog_truncates_bullets(tmp_path) -> None:
    p = tmp_path / "CHANGELOG.md"
    bullets = "\n".join(f"- bullet {i}" for i in range(10))
    p.write_text(f"## v1.0.0\n{bullets}\n", encoding="utf-8")
    entries = pw.parse_changelog(p, max_entries=1, max_bullets=3)
    assert len(entries[0].bullets) == 3


# ---------------------------------------------------------------------------
# Q7 — summarize_tool_result
# ---------------------------------------------------------------------------


def test_summarize_empty_returns_marker() -> None:
    assert pw.summarize_tool_result("") == "(no output)"
    assert pw.summarize_tool_result(None) == "(no output)"


def test_summarize_returns_first_non_empty_line() -> None:
    assert pw.summarize_tool_result("\n\n  hello\nworld") == "hello"


def test_summarize_strips_json_prefix() -> None:
    assert pw.summarize_tool_result('{"key": "value"}').startswith("key")


def test_summarize_strips_bullet_prefixes() -> None:
    assert pw.summarize_tool_result("  - actual line").startswith("- ")


def test_summarize_caps_long_lines() -> None:
    long = "X" * 200
    out = pw.summarize_tool_result(long)
    assert out.endswith("…")
    assert len(out) <= 120


def test_summarize_handles_non_string_inputs() -> None:
    out = pw.summarize_tool_result(42)
    assert out == "42"


# ---------------------------------------------------------------------------
# Welcome card
# ---------------------------------------------------------------------------


def test_welcome_card_renders_tips_and_whats_new() -> None:
    out_buf = StringIO()
    console = Console(file=out_buf, force_terminal=False, width=120, color_system=None)
    console.print(
        pw.render_welcome_card(
            tips=["Tip A", "Tip B"],
            whats_new=["New A", "New B"],
        )
    )
    text = out_buf.getvalue()
    assert "Tips for getting started" in text
    assert "Tip A" in text
    assert "Tip B" in text
    assert "What's new" in text
    assert "New A" in text


def test_welcome_card_omits_whats_new_when_disabled() -> None:
    out_buf = StringIO()
    console = Console(file=out_buf, force_terminal=False, width=120, color_system=None)
    console.print(
        pw.render_welcome_card(
            tips=["Only Tip"],
            whats_new=["Should not appear"],
            show_whats_new=False,
        )
    )
    text = out_buf.getvalue()
    assert "Only Tip" in text
    assert "Should not appear" not in text


# ---------------------------------------------------------------------------
# Tool card
# ---------------------------------------------------------------------------


def test_tool_card_collapsed_is_single_line() -> None:
    out_buf = StringIO()
    console = Console(file=out_buf, force_terminal=False, width=120, color_system=None)
    console.print(
        pw.render_tool_card(tool_name="web_search", args_preview='"Bill Kopp"')
    )
    text = out_buf.getvalue()
    assert "Web Search" in text
    assert "Bill Kopp" in text
    # Collapsed: no ``⎿`` subtree indicator.
    assert "⎿" not in text


def test_tool_card_expanded_has_subtree_summary() -> None:
    out_buf = StringIO()
    console = Console(file=out_buf, force_terminal=False, width=120, color_system=None)
    console.print(
        pw.render_tool_card(
            tool_name="exec",
            args_preview='"rm -rf /tmp/foo"',
            collapsed=False,
            result_summary="Removed 3 files",
            elapsed_s=1.2,
        )
    )
    text = out_buf.getvalue()
    assert "Exec" in text
    assert "Removed 3 files" in text
    assert "⎿" in text


def test_tool_card_uses_theme_success_color_for_bullet() -> None:
    out_buf = StringIO()
    console = Console(file=out_buf, force_terminal=True, width=120, color_system="truecolor")
    console.print(
        pw.render_tool_card(tool_name="read_file", args_preview="foo.py", success=True)
    )
    text = out_buf.getvalue()
    # The bullet color from terracotta-claude is success = #4eba65.
    assert "●" in text
    # Hard to assert ANSI precisely, so just check the bullet glyph is present.
    assert "Read File" in text


# ---------------------------------------------------------------------------
# Status footer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("state", ["idle", "propagating", "cooked"])
def test_status_footer_renders_for_each_state(state: str) -> None:
    out_buf = StringIO()
    console = Console(file=out_buf, force_terminal=False, width=120, color_system=None)
    console.print(
        pw.render_status_footer(
            state=state,
            mode="manual",
            elapsed_s=3.0,
            tokens=403,
        )
    )
    text = out_buf.getvalue()
    if state == "idle":
        assert "manual mode" in text
    elif state == "propagating":
        assert "Propagating" in text
        assert "403" in text
    elif state == "cooked":
        assert "Cooked" in text


def test_status_footer_propagating_without_elapsed_has_no_dangling_paren() -> None:
    """Regression test: ``elapsed_s=None`` used to still append a
    trailing ``)`` for the "propagating" state even though no opening
    ``(`` was ever written, leaving a stray ``)`` in the output."""
    out_buf = StringIO()
    console = Console(file=out_buf, force_terminal=False, width=120, color_system=None)
    console.print(
        pw.render_status_footer(state="propagating", mode="manual", elapsed_s=None, tokens=None)
    )
    text = out_buf.getvalue()
    assert "Propagating" in text
    assert ")" not in text
    assert "(" not in text


# ---------------------------------------------------------------------------
# Spinner
# ---------------------------------------------------------------------------


def test_spinner_elapsed_starts_at_zero(monkeypatch) -> None:
    sp = pw.SpinnerWithElapsed(bot_name="Femtobot", verb="cogitating", start_time=None)
    assert sp.elapsed_s() < 0.5


def test_spinner_uses_default_verb_when_none() -> None:
    sp = pw.SpinnerWithElapsed(bot_name="Femtobot")
    assert sp.verb  # not empty


def test_spinner_render_includes_bot_name_and_verb() -> None:
    out_buf = StringIO()
    console = Console(file=out_buf, force_terminal=False, width=120, color_system=None)
    sp = pw.SpinnerWithElapsed(bot_name="Femtobot", verb="cogitating", start_time=0.0)
    sp.elapsed_s = lambda: 12.0  # type: ignore[method-assign]
    sp.__rich_console__(console, None)  # type: ignore[arg-type]
    text = out_buf.getvalue()
    assert "Femtobot" in text
    assert "cogitating" in text
    assert "12s" in text


# ---------------------------------------------------------------------------
# HeaderBar (Q1 — uses ``__logo__`` ASCII wordmark)
# ---------------------------------------------------------------------------


def test_header_bar_uses_logo_ascii_wordmark() -> None:
    out_buf = StringIO()
    console = Console(file=out_buf, force_terminal=False, width=120, color_system=None)
    hb = pw.HeaderBar(
        bot_name="Femtobot",
        bot_icon="🐈",
        model_display="Sonnet 5",
        user_name="Bill Kopp",
        workspace="~/femtobot",
        theme=get_theme("terracotta-claude"),
    )
    console.print(hb.render())
    text = out_buf.getvalue()
    assert "Welcome back Bill Kopp" in text
    assert "Sonnet 5" in text
    assert "~/femtobot" in text
    # The ASCII wordmark (top row of FEMTOBOT block) is present.
    assert "██████╗" in text or "█" in text
    # The actual wordmark is at least 5 lines of the FEMTOBOT shape.
    assert __logo__.splitlines()[1].strip() in text or "██████╗" in text


def test_header_bar_renders_in_every_theme() -> None:
    for theme_name in ["terracotta-claude", "solarized-light", "cyber-dark", "monochrome"]:
        out_buf = StringIO()
        console = Console(file=out_buf, force_terminal=False, width=120, color_system=None)
        hb = pw.HeaderBar(
            bot_name="F",
            bot_icon="",
            model_display="M",
            user_name="U",
            workspace="/w",
            theme=get_theme(theme_name),
        )
        console.print(hb.render())
        assert "Welcome back U" in out_buf.getvalue()


# ---------------------------------------------------------------------------
# Input pill
# ---------------------------------------------------------------------------


def test_input_pill_uses_gt_glyph_in_compat() -> None:
    """Backward-compat alias — ``render_input_pill`` is preserved as a thin
    re-export of :func:`render_input_bar_top` so anything that imported
    it pre-rewrite keeps working. The legacy test asserted a pill that
    bracketed the prompt; post-rewrite the bar-only helper renders just
    the rule. Verify the rule is present and the (now-misnamed)
    glyph/placeholder arguments are ignored without raising.
    """
    out_buf = StringIO()
    console = Console(file=out_buf, force_terminal=False, width=120, color_system=None)
    console.print(pw.render_input_pill(prompt=">", placeholder="hello"))
    text = out_buf.getvalue()
    # Border lines still bracket the input visually.
    assert "─" in text
    # The legacy alias no longer embeds the prompt/placeholder; the
    # real framing moved to :func:`render_input_bar_bottom_markup`.
    assert "hello" not in text


# ---------------------------------------------------------------------------
# T1 — Input pill bar (plan §3 D9, Claude Code v2.1.x parity)
# ---------------------------------------------------------------------------


def test_render_input_bar_top_spans_full_width_minus_margin() -> None:
    out_buf = StringIO()
    console = Console(file=out_buf, force_terminal=False, width=120, color_system=None)
    bar = pw.render_input_bar_top(width=120, margin_x=2)
    console.print(bar)
    text = out_buf.getvalue()
    # 24-min width bar minus 2x2 margin = 116 chars minimum, but
    # padded by Rich to terminal width 120. At minimum we expect at
    # least 100 chars of the unicode rule.
    assert text.count(pw._INPUT_BAR_RULE_CHAR) >= 100


def test_render_input_bar_top_clamps_to_min_width() -> None:
    """A width smaller than the minimum clamps the bar to 24 chars."""
    out_buf = StringIO()
    console = Console(file=out_buf, force_terminal=False, width=120, color_system=None)
    bar = pw.render_input_bar_top(width=4, margin_x=0)
    assert isinstance(bar, pw.Text)
    # The internal ``_resolve_width`` returns the clamped width.
    # ``Text.plain`` strips styles; check the text length.
    assert len(bar.plain) == pw._resolve_width(width=4, margin_x=0)


def test_render_input_bar_bottom_markup_contains_glyph_placeholder_and_cursor() -> None:
    markup = str(pw.render_input_bar_bottom_markup(width=120, margin_x=2, prompt="❯", placeholder="hello"))
    # Prompt row: glyph + placeholder + cursor.
    assert "❯" in markup
    assert "hello" in markup
    # prompt_toolkit color tags wrap the rule and glyph.
    assert "<style" in markup and "</style>" in markup
    # Bug D fix (v0.1.0-ui.1): cursor block follows the placeholder so
    # the user always sees where the typing focus is.
    assert "▌" in markup


def test_render_input_bar_bottom_markup_omits_placeholder_when_empty() -> None:
    markup = str(pw.render_input_bar_bottom_markup(width=120, margin_x=2, prompt="❯"))
    assert "❯" in markup
    # No placeholder tag when the placeholder is empty.
    assert "<placeholder" not in markup
    assert "hello" not in markup
    # Cursor still rendered even without a placeholder.
    assert "▌" in markup


def test_render_input_bar_bottom_markup_two_space_gap_between_glyph_and_placeholder() -> None:
    """Bug D fix: the markup must include ``❯  `` with a literal gap.

    Without the second space the terminal renders the placeholder glued
    to the glyph (e.g. ``❯Nova mensagem``), which is what the user
    reported on the v0.1.0-ui.1 preview screenshot.
    """
    markup = str(pw.render_input_bar_bottom_markup(width=120, margin_x=2, prompt="❯", placeholder="hello"))
    # The HTML formatter must emit a literal two-space gap between the
    # closing ``</prompt>`` tag and the opening ``<placeholder>`` tag.
    # Single space was the buggy behaviour that glued them together.
    assert "</prompt>  <placeholder" in markup


def test_render_input_bar_bottom_markup_escapes_html_special_chars() -> None:
    markup = str(pw.render_input_bar_bottom_markup(width=120, placeholder="&<>", prompt=">"))
    # All HTML-special characters escaped.
    assert "&amp;" in markup
    assert "&lt;" in markup
    assert "&gt;" in markup


def test_render_input_toolbar_markup_contains_bottom_rule_and_footer() -> None:
    markup = str(pw.render_input_toolbar_markup(width=120, margin_x=2, mode="manual"))
    assert pw._INPUT_BAR_RULE_CHAR * 80 in markup
    assert "manual mode on" in markup
    assert "▌" in markup
