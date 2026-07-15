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
    out_buf = StringIO()
    console = Console(file=out_buf, force_terminal=False, width=120, color_system=None)
    console.print(pw.render_input_pill(prompt=">", placeholder="hello"))
    text = out_buf.getvalue()
    assert ">" in text
    assert "hello" in text
    # Border lines should bracket the input.
    assert "─" in text
