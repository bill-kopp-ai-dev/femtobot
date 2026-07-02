"""Tests for the role_renderer module (Camada 4 — UX fixes).

Covers issues UX-1 (turn gap) and UX-2 (role header / user separator).
"""

from __future__ import annotations

from io import StringIO
from types import SimpleNamespace

from rich.console import Console

from femtobot.cli.role_renderer import (
    DEFAULT_GAP,
    MAX_GAP,
    MIN_GAP,
    TurnSpacingRenderer,
    role_header,
    turn_gap,
    user_separator_line,
)


# ---------------------------------------------------------------------------
# role_header
# ---------------------------------------------------------------------------


def test_role_header_always_default() -> None:
    """Default mode is 'always' — header contains bot name and emoji."""
    h = role_header("Femtobot")
    assert "Femtobot" in h.plain
    assert "🤖" in h.plain
    assert "▌" in h.plain  # visual bar marker


def test_role_header_minimal_has_only_emoji() -> None:
    h = role_header("Femtobot", mode="minimal")
    assert "🤖" in h.plain
    assert "Femtobot" not in h.plain


def test_role_header_off_is_empty() -> None:
    h = role_header("Femtobot", mode="off")
    assert h.plain == ""


def test_role_header_invalid_mode_falls_back_to_always() -> None:
    h = role_header("Femtobot", mode="bogus")
    assert "Femtobot" in h.plain  # default mode applied


def test_role_header_custom_icon() -> None:
    h = role_header("Claude", bot_icon="🟣", mode="always")
    assert "🟣" in h.plain
    assert "Claude" in h.plain


# ---------------------------------------------------------------------------
# user_separator_line
# ---------------------------------------------------------------------------


def test_user_separator_default_chars() -> None:
    sep = user_separator_line(width=20)
    assert "·" in sep.plain
    # roughly 20 chars (each "· " is 2 chars but we rstrip)
    assert len(sep.plain) > 0


def test_user_separator_disabled_returns_empty() -> None:
    sep = user_separator_line(width=40, enabled=False)
    assert sep.plain == ""


def test_user_separator_zero_width_returns_empty() -> None:
    sep = user_separator_line(width=0, enabled=True)
    assert sep.plain == ""


def test_user_separator_styling_is_dim() -> None:
    sep = user_separator_line(width=10)
    # Style must include 'dim' for low-attention rendering.
    style_blob = str(sep.style)
    assert "dim" in style_blob.lower()


# ---------------------------------------------------------------------------
# turn_gap
# ---------------------------------------------------------------------------


def test_turn_gap_default_is_one_blank() -> None:
    assert turn_gap() == [""]


def test_turn_gap_explicit_zero() -> None:
    assert turn_gap(0) == []


def test_turn_gap_explicit_three() -> None:
    assert turn_gap(3) == ["", "", ""]


def test_turn_gap_clamps_above_max() -> None:
    """Values above MAX_GAP are clamped to MAX_GAP (no unbounded growth)."""
    assert turn_gap(99) == [""] * MAX_GAP


def test_turn_gap_clamps_below_min() -> None:
    """Negative values are clamped to MIN_GAP (0)."""
    assert turn_gap(-3) == []


def test_turn_gap_none_uses_default() -> None:
    assert len(turn_gap(None)) == DEFAULT_GAP


# ---------------------------------------------------------------------------
# TurnSpacingRenderer
# ---------------------------------------------------------------------------


def _capture_console() -> tuple[Console, StringIO]:
    buf = StringIO()
    console = Console(file=buf, width=80, force_terminal=False, color_system=None)
    return console, buf


def test_spacing_renderer_prints_role_header_in_always_mode() -> None:
    console, buf = _capture_console()
    spacing = TurnSpacingRenderer(
        gap_after_turn=1,
        role_header_mode="always",
        user_separator=True,
        accent_color="#ff0000",
        bot_name="Femtobot",
        turn_box=False,  # legacy bar style for this test
    )
    spacing.print_role_header(console)
    out = buf.getvalue()
    assert "Femtobot" in out
    assert "🤖" in out


def test_spacing_renderer_prints_role_header_in_box_mode() -> None:
    """Camada 5 — when turn_box=True, the header becomes ``[🤖 Femtobot]``."""
    console, buf = _capture_console()
    spacing = TurnSpacingRenderer(
        gap_after_turn=1,
        role_header_mode="always",
        user_separator=True,
        accent_color="#d77757",
        bot_name="Femtobot",
        turn_box=True,
    )
    spacing.print_role_header(console)
    out = buf.getvalue()
    assert "[" in out and "]" in out
    assert "Femtobot" in out


def test_spacing_renderer_skips_role_header_when_off() -> None:
    console, buf = _capture_console()
    spacing = TurnSpacingRenderer(
        gap_after_turn=0,
        role_header_mode="off",
        user_separator=False,
        turn_box=False,
    )
    spacing.print_role_header(console)
    out = buf.getvalue()
    assert out.strip() == ""


def test_spacing_renderer_user_box_no_op_when_disabled() -> None:
    """``print_user_box`` should be a no-op when ``turn_box=False``."""
    console, buf = _capture_console()
    spacing = TurnSpacingRenderer(turn_box=False)
    spacing.print_user_box(console)
    assert buf.getvalue().strip() == ""


def test_spacing_renderer_user_box_default() -> None:
    """With ``turn_box=True``, the user box prints ``[👤 You]``."""
    console, buf = _capture_console()
    spacing = TurnSpacingRenderer(turn_box=True)
    spacing.print_user_box(console)
    out = buf.getvalue()
    assert "[" in out and "]" in out
    assert "You" in out


def test_spacing_renderer_input_gap_default() -> None:
    """Default ``gap_before_input`` should produce 2 blank lines."""
    console, buf = _capture_console()
    spacing = TurnSpacingRenderer(gap_before_input=2)
    spacing.print_input_gap(console)
    assert buf.getvalue().endswith("\n\n")


def test_spacing_renderer_margin_default_is_4() -> None:
    """Camada 5 — margin_x defaults to 4 chars."""
    spacing = TurnSpacingRenderer()
    assert spacing.margin_x == 4


def test_spacing_renderer_apply_margin_returns_console() -> None:
    """apply_margin should return a Console with reduced width."""
    parent = Console(file=__import__("io").StringIO(), width=80, force_terminal=False)
    spacing = TurnSpacingRenderer(margin_x=2)
    child = spacing.apply_margin(parent)
    # New width is parent.width - 2 * margin_x = 80 - 4 = 76
    assert child.width == 76


def test_spacing_renderer_apply_margin_min_width_clamp() -> None:
    """When parent.width <= margin*2, the width is clamped to MIN_OUTPUT_WIDTH.

    Widths too small for the requested padding must not crash and must
    not produce an unreadable console.
    """
    parent = Console(file=__import__("io").StringIO(), width=10, force_terminal=False)
    spacing = TurnSpacingRenderer(margin_x=4)
    child = spacing.apply_margin(parent)
    # width would have gone below 40 → clamp to 40
    assert child.width == 40


def test_spacing_renderer_skips_user_separator_when_disabled() -> None:
    console, buf = _capture_console()
    spacing = TurnSpacingRenderer(
        gap_after_turn=0,
        role_header_mode="always",
        user_separator=False,
    )
    spacing.print_user_separator(console)
    out = buf.getvalue()
    assert out.strip() == ""


def test_spacing_renderer_turn_gap_produces_blank_line() -> None:
    console, buf = _capture_console()
    spacing = TurnSpacingRenderer(gap_after_turn=2)
    spacing.print_turn_gap(console)
    # Rich's console.print("") emits one newline per call. With gap=2 we
    # expect two newlines in the captured buffer.
    out = buf.getvalue()
    assert out.endswith("\n\n")


def test_spacing_renderer_from_config_reads_block() -> None:
    """``from_config`` should pick up the nested agents.cli.* values."""
    cfg = SimpleNamespace(
        agents=SimpleNamespace(
            defaults=SimpleNamespace(
                cli=SimpleNamespace(
                    gap_after_turn=2,
                    role_header="minimal",
                    user_separator=False,
                )
            )
        )
    )
    spacing = TurnSpacingRenderer.from_config(cfg)
    assert spacing.gap_after_turn == 2
    assert spacing.role_header_mode == "minimal"
    assert spacing.user_separator is False


def test_spacing_renderer_from_config_uses_defaults_on_missing() -> None:
    """Empty config object → defaults (1 / always / True)."""
    cfg = SimpleNamespace()  # no .agents attribute
    spacing = TurnSpacingRenderer.from_config(cfg)
    assert spacing.gap_after_turn == DEFAULT_GAP
    assert spacing.role_header_mode == "always"
    assert spacing.user_separator is True


def test_spacing_renderer_overrides_take_precedence() -> None:
    """Explicit kwargs override what ``from_config`` reads."""
    cfg = SimpleNamespace(
        agents=SimpleNamespace(
            defaults=SimpleNamespace(
                cli=SimpleNamespace(
                    gap_after_turn=3,
                    role_header="off",
                    user_separator=False,
                )
            )
        )
    )
    spacing = TurnSpacingRenderer.from_config(cfg, gap_after_turn=0)
    assert spacing.gap_after_turn == 0  # override
    assert spacing.role_header_mode == "off"  # from config