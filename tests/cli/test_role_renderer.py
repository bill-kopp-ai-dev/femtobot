"""Tests for the role_renderer module (Camada 4 — UX fixes).

Covers issues UX-1 (turn gap) and UX-2 (role header / user separator).
"""

from __future__ import annotations

from io import StringIO
from types import SimpleNamespace

from rich.console import Console
from rich.text import Text

from femtobot.cli.role_renderer import (
    DEFAULT_GAP,
    DEFAULT_HEADER_MODE,
    DEFAULT_INPUT_GAP,
    DEFAULT_MARGIN,
    DEFAULT_TURN_BOX,
    DEFAULT_USER_SEPARATOR,
    MAX_GAP,
    MAX_INPUT_GAP,
    MAX_MARGIN,
    MIN_GAP,
    MIN_INPUT_GAP,
    MIN_MARGIN,
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


def test_turn_gap_explicit_max() -> None:
    """MAX_GAP blanks lines exactly."""
    assert turn_gap(MAX_GAP) == [""] * MAX_GAP


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


def test_spacing_renderer_margin_default_is_2() -> None:
    """Camada 5 — margin_x defaults to 2 chars (minimum required by P1)."""
    spacing = TurnSpacingRenderer()
    assert spacing.margin_x == 2


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


# ---------------------------------------------------------------------------
# Camada 5 — margin on role header / user box / separator
# ---------------------------------------------------------------------------
# These cover the P1-fix follow-up: agent/user boxes and the
# "· · ·" separator must also receive the lateral margin so they line
# up with the agent reply (which gets Padding via StreamRenderer).
# Without this, the bracketed boxes sit flush against the terminal's
# left edge while the reply stays indented — visually inconsistent.
# ---------------------------------------------------------------------------


def test_role_header_box_includes_margin_left_padding() -> None:
    """``print_role_header`` prefixes ``margin_x`` spaces to the box.

    Regression test for the user-reported "boxes still glued to the
    terminal edge while agent reply is indented".
    """
    console, buf = _capture_console()
    spacing = TurnSpacingRenderer(
        gap_after_turn=1,
        role_header_mode="always",
        user_separator=True,
        accent_color="#d77757",
        bot_name="Femtobot",
        turn_box=True,
        margin_x=4,
    )
    spacing.print_role_header(console)
    out = buf.getvalue()
    # 4 spaces of margin + the bracketed box content.
    assert out.startswith("    [")
    assert "Femtobot" in out


def test_user_box_includes_margin_left_padding() -> None:
    """``print_user_box`` prefixes ``margin_x`` spaces to the user box."""
    console, buf = _capture_console()
    spacing = TurnSpacingRenderer(
        gap_after_turn=1,
        role_header_mode="always",
        user_separator=True,
        margin_x=4,
        turn_box=True,
    )
    spacing.print_user_box(console)
    out = buf.getvalue()
    assert out.startswith("    [")
    assert "You" in out


def test_user_separator_includes_margin_left_padding() -> None:
    """``print_user_separator`` prefixes ``margin_x`` spaces to the divider."""
    console, buf = _capture_console()
    spacing = TurnSpacingRenderer(
        gap_after_turn=1,
        role_header_mode="always",
        user_separator=True,
        margin_x=4,
    )
    spacing.print_user_separator(console, width=20)
    out = buf.getvalue()
    # 4 spaces of margin + the divider body (which itself starts with "·").
    assert out.startswith("    ·")


def test_min_margin_emits_minimum_left_padding() -> None:
    """``margin_x=CLI_MIN_MARGIN`` produces exactly that many spaces.

    The minimum margin (currently 2) enforces P1: text must never sit
    flush against the terminal's left edge. The renderer normalizes
    smaller values up to the minimum.
    """
    from femtobot.config.schema import CLI_MIN_MARGIN

    console, buf = _capture_console()
    spacing = TurnSpacingRenderer(
        gap_after_turn=1,
        role_header_mode="always",
        user_separator=True,
        accent_color="#d77757",
        bot_name="Femtobot",
        turn_box=True,
        margin_x=CLI_MIN_MARGIN,
    )
    spacing.print_role_header(console)
    spacing.print_user_box(console)
    out = buf.getvalue()
    # Exactly CLI_MIN_MARGIN chars of leading whitespace.
    assert out.startswith(" " * CLI_MIN_MARGIN + "[")
    assert "Femtobot" in out


def test_below_min_margin_is_clamped_up() -> None:
    """``margin_x < CLI_MIN_MARGIN`` is clamped up to the minimum.

    We don't allow ``margin_x=0`` because that would defeat P1. Users
    who insist on no padding can edit ``CLI_MIN_MARGIN`` directly.
    """
    from femtobot.config.schema import CLI_MIN_MARGIN

    console, buf = _capture_console()
    spacing = TurnSpacingRenderer(
        gap_after_turn=1,
        role_header_mode="always",
        user_separator=True,
        accent_color="#d77757",
        bot_name="Femtobot",
        turn_box=True,
        margin_x=0,
    )
    spacing.print_role_header(console)
    out = buf.getvalue()
    # 0 was clamped up to CLI_MIN_MARGIN (2) — header gets 2 spaces of padding.
    assert out.startswith(" " * CLI_MIN_MARGIN + "[")


def test_padding_helper_clamps_above_max_margin() -> None:
    """``_pad_left`` clamps the margin to ``CLI_MAX_MARGIN``.

    Prevents a user typo (`margin_x=99`) from injecting 99 chars of
    whitespace and pushing the box off the right edge of the terminal.
    """
    from femtobot.cli.role_renderer import _pad_left
    from femtobot.config.schema import CLI_MAX_MARGIN

    txt = _pad_left(Text("hello"), 99)
    assert txt.plain.startswith(" " * CLI_MAX_MARGIN + "hello")
    assert len(txt.plain) == CLI_MAX_MARGIN + len("hello")


def test_padding_helper_zero_is_clamped_to_min() -> None:
    """``_pad_left`` clamps ``margin=0`` up to ``CLI_MIN_MARGIN``.

    The minimum margin enforces P1: text must never sit flush against
    the terminal's left edge. ``margin=None`` falls through to the
    schema default (:data:`CLI_DEFAULT_MARGIN_X`).
    """
    from femtobot.cli.role_renderer import _pad_left
    from femtobot.config.schema import (
        CLI_DEFAULT_MARGIN_X,
        CLI_MIN_MARGIN,
    )

    base = Text("hello")
    # ``margin=0`` is clamped up to the minimum (2 chars).
    result_zero = _pad_left(base, 0)
    assert result_zero.plain.startswith(" " * CLI_MIN_MARGIN + "hello")
    # ``None`` → schema default (currently 2 chars).
    result_none = _pad_left(base, None)
    assert result_none.plain.startswith(" " * CLI_DEFAULT_MARGIN_X + "hello")


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


# ---------------------------------------------------------------------------
# Schema ↔ role_renderer linkage
# ---------------------------------------------------------------------------
# These tests guard against the previous failure mode where the
# module-level constants in role_renderer were dead code (never read by
# the runtime). The schema is now the single source of truth and the
# role_renderer constants are aliases — these tests pin that contract.
# ---------------------------------------------------------------------------


def test_module_constants_are_aliases_of_schema_defaults() -> None:
    """role_renderer constants must be the *same object* as the schema defaults.

    Identity (==, not ==) so a drift between the two surfaces immediately
    during a refactor.
    """
    from femtobot.config.schema import (
        CLI_DEFAULT_GAP_AFTER_TURN,
        CLI_DEFAULT_GAP_BEFORE_INPUT,
        CLI_DEFAULT_MARGIN_X,
        CLI_DEFAULT_ROLE_HEADER_MODE,
        CLI_DEFAULT_TURN_BOX,
        CLI_DEFAULT_USER_SEPARATOR,
        CLI_MAX_GAP,
        CLI_MAX_INPUT_GAP,
        CLI_MAX_MARGIN,
        CLI_MIN_GAP,
        CLI_MIN_INPUT_GAP,
        CLI_MIN_MARGIN,
    )

    assert DEFAULT_GAP is CLI_DEFAULT_GAP_AFTER_TURN
    assert DEFAULT_HEADER_MODE is CLI_DEFAULT_ROLE_HEADER_MODE
    assert DEFAULT_USER_SEPARATOR is CLI_DEFAULT_USER_SEPARATOR
    assert DEFAULT_MARGIN is CLI_DEFAULT_MARGIN_X
    assert DEFAULT_INPUT_GAP is CLI_DEFAULT_GAP_BEFORE_INPUT
    assert DEFAULT_TURN_BOX is CLI_DEFAULT_TURN_BOX
    assert MIN_GAP is CLI_MIN_GAP
    assert MAX_GAP is CLI_MAX_GAP
    assert MIN_MARGIN is CLI_MIN_MARGIN
    assert MAX_MARGIN is CLI_MAX_MARGIN
    assert MIN_INPUT_GAP is CLI_MIN_INPUT_GAP
    assert MAX_INPUT_GAP is CLI_MAX_INPUT_GAP


def test_cli_config_defaults_match_schema_constants() -> None:
    """CliConfig() must inherit the schema default values verbatim."""
    from femtobot.config.schema import (
        CLI_DEFAULT_GAP_AFTER_TURN,
        CLI_DEFAULT_GAP_BEFORE_INPUT,
        CLI_DEFAULT_MARGIN_X,
        CLI_DEFAULT_ROLE_HEADER_MODE,
        CLI_DEFAULT_TURN_BOX,
        CLI_DEFAULT_USER_SEPARATOR,
        CliConfig,
    )

    cli = CliConfig()
    assert cli.gap_after_turn == CLI_DEFAULT_GAP_AFTER_TURN
    assert cli.role_header == CLI_DEFAULT_ROLE_HEADER_MODE
    assert cli.user_separator is CLI_DEFAULT_USER_SEPARATOR
    assert cli.margin_x == CLI_DEFAULT_MARGIN_X
    assert cli.gap_before_input == CLI_DEFAULT_GAP_BEFORE_INPUT
    assert cli.turn_box is CLI_DEFAULT_TURN_BOX


def test_schema_field_defaults_capture_schema_constants() -> None:
    """CliConfig field defaults are the schema constants (captured at class
    definition time, by design).

    The actual runtime override paths (env vars, /style slash command,
    config.json) all work at Pydantic instantiation or via live mutation
    on the config object — those are tested elsewhere. This test pins
    the *field default* contract so a future refactor that breaks it
    (e.g. reintroducing hard-coded literals in CliConfig) is caught.
    """
    from femtobot.config.schema import (
        CLI_DEFAULT_GAP_AFTER_TURN,
        CLI_DEFAULT_GAP_BEFORE_INPUT,
        CLI_DEFAULT_MARGIN_X,
        CLI_DEFAULT_ROLE_HEADER_MODE,
        CLI_DEFAULT_TURN_BOX,
        CLI_DEFAULT_USER_SEPARATOR,
        CliConfig,
    )

    fields = CliConfig.model_fields
    assert fields["gap_after_turn"].default == CLI_DEFAULT_GAP_AFTER_TURN
    assert fields["role_header"].default == CLI_DEFAULT_ROLE_HEADER_MODE
    assert fields["user_separator"].default is CLI_DEFAULT_USER_SEPARATOR
    assert fields["margin_x"].default == CLI_DEFAULT_MARGIN_X
    assert fields["gap_before_input"].default == CLI_DEFAULT_GAP_BEFORE_INPUT
    assert fields["turn_box"].default is CLI_DEFAULT_TURN_BOX


def test_cli_spacing_bounds_match_documented_ranges() -> None:
    """Pin the exact bounds so a regression that changes them surfaces
    immediately and the JSON schema / Field descriptions stay honest.

    Documented ranges:
      - ``gap_after_turn``     — 0..2 (blank lines after each turn)
      - ``margin_x``           — 2..4 (lateral padding, enforces P1)
      - ``gap_before_input``   — 0..4 (blank lines before the prompt)
    """
    from femtobot.config.schema import (
        CLI_MAX_GAP,
        CLI_MAX_INPUT_GAP,
        CLI_MAX_MARGIN,
        CLI_MIN_GAP,
        CLI_MIN_INPUT_GAP,
        CLI_MIN_MARGIN,
    )

    # gap_after_turn: 0..2
    assert CLI_MIN_GAP == 0
    assert CLI_MAX_GAP == 2
    # margin_x: 2..4 (P1 enforces a minimum visual margin so text
    # doesn't sit flush against the terminal edge).
    assert CLI_MIN_MARGIN == 2
    assert CLI_MAX_MARGIN == 4
    # gap_before_input: 0..4
    assert CLI_MIN_INPUT_GAP == 0
    assert CLI_MAX_INPUT_GAP == 4


def test_cli_spacing_defaults_match_documented_values() -> None:
    """Pin the exact default values so a regression that bumps them
    surfaces immediately.

    Values must match:
      - ``gap_after_turn``     = 1  (one blank line after each turn)
      - ``margin_x``           = 2  (2 chars of lateral padding)
      - ``gap_before_input``   = 0  (no extra blank lines before prompt)
    """
    from femtobot.config.schema import (
        CLI_DEFAULT_GAP_AFTER_TURN,
        CLI_DEFAULT_GAP_BEFORE_INPUT,
        CLI_DEFAULT_MARGIN_X,
    )

    assert CLI_DEFAULT_GAP_AFTER_TURN == 1
    assert CLI_DEFAULT_MARGIN_X == 2
    assert CLI_DEFAULT_GAP_BEFORE_INPUT == 0


def test_spacing_field_descriptions_are_present_and_informative() -> None:
    """Every spacing knob on CliConfig must carry a ``Field(description=...)``.

    The description is what shows up in JSON schemas and IDE tooltips, so
    a missing or empty description here is a documentation regression
    (users wouldn't know what the knob does or what range is valid).
    """
    from femtobot.config.schema import CliConfig

    spacing_fields = (
        "gap_after_turn",
        "role_header",
        "user_separator",
        "margin_x",
        "gap_before_input",
        "turn_box",
    )
    # Each description should be at least 30 chars of useful prose. Long
    # enough to actually describe the knob; short enough to not be a
    # placeholder. We also check the integer-typed knobs explicitly carry
    # "Range:" because that's the most useful piece of info for them.
    int_fields = ("gap_after_turn", "margin_x", "gap_before_input")
    for name in spacing_fields:
        field = CliConfig.model_fields[name]
        desc = (field.description or "").strip()
        assert len(desc) >= 30, (
            f"{name} description is too short: {desc!r}"
        )
        if name in int_fields:
            assert "Range:" in desc, (
                f"{name} is an int knob but its description lacks 'Range:': {desc!r}"
            )
