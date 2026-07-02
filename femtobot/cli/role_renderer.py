"""Per-turn role rendering and turn-spacing for the Femtobot CLI.

Addresses two UX complaints reported in Camada 4:

  UX-1 — Last agent message sits glued to the bottom of the terminal,
         making the next ``You:`` prompt uncomfortable to read.

  UX-2 — Human and agent messages look visually similar; the user
         can struggle to identify which side said what at a glance.

This module produces three small, pure helpers:

  :func:`role_header` — the line printed **before** an agent turn starts.
    Default: ``🤖 Femtobot ▌`` on a colored bar.
  :func:`user_separator_line` — a thin dim divider printed after the
    user's input so the agent reply is clearly framed.
  :func:`turn_gap` — N blank lines printed after each completed turn
    so the prompt has room to breathe.

All rendering respects the active ``agents.cli.*`` block:

  ``gap_after_turn`` — int 0..3 (default 1)
  ``role_header``    — 'always' | 'minimal' | 'off' (default 'always')
  ``user_separator`` — bool (default True)

Design rule: no production code outside ``stream.py`` should care about
these settings. The helpers here are pure (no I/O), testable, and safe
to call even when the config is missing.
"""

from __future__ import annotations

from rich.console import Console, RenderableType
from rich.text import Text

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# These names are *aliases* of the canonical defaults in
# ``femtobot.config.schema`` (the single source of truth for the CLI
# spacing knobs). Editing the schema constants changes the runtime
# defaults everywhere — no more dead constants.
#
# See the ``CLI_DEFAULT_*`` block at the top of ``config/schema.py`` for
# override order (env vars, .env, /style slash command, schema defaults).
from femtobot.config.schema import (
    CLI_DEFAULT_GAP_AFTER_TURN as DEFAULT_GAP,
    CLI_DEFAULT_GAP_BEFORE_INPUT as DEFAULT_INPUT_GAP,
    CLI_DEFAULT_MARGIN_X as DEFAULT_MARGIN,
    CLI_DEFAULT_ROLE_HEADER_MODE as DEFAULT_HEADER_MODE,
    CLI_DEFAULT_TURN_BOX as DEFAULT_TURN_BOX,
    CLI_DEFAULT_USER_SEPARATOR as DEFAULT_USER_SEPARATOR,
    CLI_MAX_GAP as MAX_GAP,
    CLI_MAX_INPUT_GAP as MAX_INPUT_GAP,
    CLI_MAX_MARGIN as MAX_MARGIN,
    CLI_MIN_GAP as MIN_GAP,
    CLI_MIN_INPUT_GAP as MIN_INPUT_GAP,
    CLI_MIN_MARGIN as MIN_MARGIN,
)

DEFAULT_GAP_AFTER_TURN = DEFAULT_GAP
VALID_HEADER_MODES = ("always", "minimal", "off")


def _normalize_gap(value: int | None) -> int:
    """Clamp the configured gap into [0, 3]."""
    if value is None:
        return DEFAULT_GAP
    return max(MIN_GAP, min(MAX_GAP, int(value)))


def _normalize_header_mode(value: str | None) -> str:
    """Return one of ``always`` / ``minimal`` / ``off`` (defaults to 'always')."""
    if value in VALID_HEADER_MODES:
        return value
    return DEFAULT_HEADER_MODE


# ---------------------------------------------------------------------------
# Pure renderers
# ---------------------------------------------------------------------------


def role_header(
    bot_name: str = "Femtobot",
    bot_icon: str = "🤖",
    *,
    mode: str = DEFAULT_HEADER_MODE,
    accent_color: str = "#d77757",
    as_box: bool = False,
) -> Text:
    """Build the per-turn role header rendered before an agent reply.

    Modes
    -----
    ``always``  — bold colored bar ``🤖 Femtobot ▌`` (default)
    ``minimal`` — emoji only, e.g. ``🤖`` (legacy Camada 1 behavior)
    ``off``     — empty renderable

    The bar uses ``accent_color`` so it picks up the active CliTheme.

    When ``as_box=True`` (Camada 5), the header is wrapped in a
    bracketed box: ``[🤖 Femtobot]``. This is the recommended visual
    for telling agent turns apart from user turns at a glance.
    """
    normalized = _normalize_header_mode(mode)
    if normalized == "off":
        return Text("")
    if normalized == "minimal":
        if as_box:
            return Text.assemble(
                ("[ ", f"bold {accent_color}"),
                (f"{bot_icon} ", "bold"),
                ("] ", "bold"),
            )
        return Text(f"{bot_icon} ", style="bold")
    # 'always'
    if as_box:
        return Text.assemble(
            ("[ ", f"bold {accent_color}"),
            (f"{bot_icon} ", "bold"),
            (f"{bot_name} ", "bold"),
            ("]", f"bold {accent_color}"),
        )
    return Text.assemble(
        (f"  {bot_icon} ", "bold"),
        (f"{bot_name} ", "bold"),
        (f"▌", f"bold {accent_color}"),
    )


def user_separator_line(width: int = 60, *, enabled: bool = True) -> Text:
    """A thin dim divider line printed after the user's input.

    Default: a row of ``·`` characters in dim gray, e.g. ``· · · · ·``.
    Set ``enabled=False`` to return an empty renderable (or
    ``user_separator = False`` in config).
    """
    if not enabled or width <= 0:
        return Text("")
    chars = "· " * (width // 2)
    return Text(chars.rstrip(), style="dim")


def turn_gap(gap: int | None = None) -> list[str]:
    """Return N blank lines (as a list of empty strings).

    ``gap`` is clamped to ``[0, 3]``. ``None`` means use the default (1).
    """
    n = _normalize_gap(gap)
    return [""] * n


# ---------------------------------------------------------------------------
# Camada 5 — visual separation helpers
# ---------------------------------------------------------------------------
# Bounds (MIN_*/MAX_*) and defaults (DEFAULT_*) are re-exported from
# ``femtobot.config.schema`` at the top of this module — single source of
# truth. The legacy per-module constants have been removed; use the
# canonical names from the schema (or from the re-exports above) instead.

# Minimum output width when applying margins. Below this the console
# becomes unreadable, so we keep the parent width unchanged.
MIN_OUTPUT_WIDTH = 40


def _normalize_margin(value: int | None) -> int:
    """Clamp margin_x into [0, 8]."""
    if value is None:
        return DEFAULT_MARGIN
    return max(MIN_MARGIN, min(MAX_MARGIN, int(value)))


def _normalize_input_gap(value: int | None) -> int:
    """Clamp gap_before_input into [0, 5]."""
    if value is None:
        return DEFAULT_INPUT_GAP
    return max(MIN_INPUT_GAP, min(MAX_INPUT_GAP, int(value)))


def margin_padding(margin: int | None = None) -> tuple[int, int]:
    """Return ``(left, right)`` padding in chars for the active console.

    Use with Rich ``Console(padding=...)`` or with `print(..., padding=...)`
    to leave breathing room on both sides of the terminal.

    ``margin`` is clamped to ``[0, 8]``.
    """
    m = _normalize_margin(margin)
    return (m, m)


def margin_line(margin: int | None = None) -> str:
    """Return ``" " * margin`` — useful when prepending indent manually."""
    m = _normalize_margin(margin)
    return " " * m


def input_gap_lines(gap: int | None = None) -> list[str]:
    """Return N blank lines to print BEFORE the ``You:`` prompt.

    ``gap`` is clamped to ``[0, 5]``.
    """
    n = _normalize_input_gap(gap)
    return [""] * n


def user_box(user_name: str = "You", user_icon: str = "👤", *, accent_color: str = "#5fafff") -> Text:
    """Render the user-turn box header.

    Default: ``[👤 You]`` in user-blue, matching the agent's box style.

    The agent-side counterpart is :func:`role_header` with ``as_box=True``.
    Together they form two visually distinct blocks (Camada 5 P3 fix).
    """
    return Text.assemble(
        ("[ ", f"bold {accent_color}"),
        (f"{user_icon} ", "bold"),
        (f"{user_name} ", "bold"),
        ("]", f"bold {accent_color}"),
    )


# ---------------------------------------------------------------------------
# One-shot printer helpers
# ---------------------------------------------------------------------------


def print_role_header(
    console: Console,
    bot_name: str = "Femtobot",
    bot_icon: str = "🤖",
    *,
    mode: str = DEFAULT_HEADER_MODE,
    accent_color: str = "#d77757",
    as_box: bool = False,
) -> None:
    """Print the role header to ``console`` (no-op when mode == 'off')."""
    header = role_header(
        bot_name=bot_name,
        bot_icon=bot_icon,
        mode=mode,
        accent_color=accent_color,
        as_box=as_box,
    )
    if not header.plain:
        return
    console.print(header)


def print_user_separator(
    console: Console,
    width: int = 60,
    *,
    enabled: bool = True,
) -> None:
    """Print the user separator line (no-op when disabled)."""
    if not enabled:
        return
    sep = user_separator_line(width=width, enabled=True)
    if not sep.plain:
        return
    console.print(sep)


def print_turn_gap(
    console: Console,
    gap: int | None = None,
) -> None:
    """Print N blank lines after a completed turn."""
    for line in turn_gap(gap):
        console.print(line)


# ---------------------------------------------------------------------------
# Configuration-aware orchestrator
# ---------------------------------------------------------------------------


class TurnSpacingRenderer:
    """Coordinates role-header + user-separator + turn-gap + margins.

    Reads the active ``agents.cli.*`` config (or accepts explicit kwargs).
    Use this from ``StreamRenderer`` so the REPL stays config-driven.

    Camada 5 adds:
      * ``margin_x`` — horizontal padding applied via console.padding
      * ``gap_before_input`` — extra blank lines before the ``You:`` prompt
      * ``turn_box`` — render the role header as ``[🤖 Femtobot]`` style
        box, paired with :func:`user_box` for the user side
    """

    def __init__(
        self,
        *,
        gap_after_turn: int | None = None,
        role_header_mode: str | None = None,
        user_separator: bool | None = None,
        accent_color: str = "#d77757",
        bot_name: str = "Femtobot",
        bot_icon: str = "🤖",
        # Camada 5 fields
        margin_x: int | None = None,
        gap_before_input: int | None = None,
        turn_box: bool | None = None,
        user_name: str = "You",
        user_icon: str = "👤",
        user_accent_color: str = "#5fafff",
    ):
        self.gap_after_turn = _normalize_gap(gap_after_turn)
        self.role_header_mode = _normalize_header_mode(role_header_mode)
        self.user_separator = (
            True if user_separator is None else bool(user_separator)
        )
        self.accent_color = accent_color
        self.bot_name = bot_name
        self.bot_icon = bot_icon
        # Camada 5
        self.margin_x = _normalize_margin(margin_x)
        self.gap_before_input = _normalize_input_gap(gap_before_input)
        self.turn_box = True if turn_box is None else bool(turn_box)
        self.user_name = user_name
        self.user_icon = user_icon
        self.user_accent_color = user_accent_color

    @classmethod
    def from_config(cls, config_obj: object, **overrides) -> "TurnSpacingRenderer":
        """Build a renderer from a Femtobot Config object.

        Reads the active ``agents.defaults.cli.*`` block. Any failure
        falls back to the module defaults (backward-compatible).
        """
        gap = mode = sep = None
        margin = input_gap = None
        turn_box: bool | None = None
        try:
            cli_cfg = getattr(
                getattr(getattr(config_obj, "agents", None), "defaults", None),
                "cli",
                None,
            )
            if cli_cfg is not None:
                gap = getattr(cli_cfg, "gap_after_turn", None)
                mode = getattr(cli_cfg, "role_header", None)
                sep = getattr(cli_cfg, "user_separator", None)
                margin = getattr(cli_cfg, "margin_x", None)
                input_gap = getattr(cli_cfg, "gap_before_input", None)
                turn_box = getattr(cli_cfg, "turn_box", None)
        except Exception:
            pass

        kwargs: dict = {
            "gap_after_turn": gap,
            "role_header_mode": mode,
            "user_separator": sep,
            "margin_x": margin,
            "gap_before_input": input_gap,
            "turn_box": turn_box,
        }
        kwargs.update(overrides)
        return cls(**kwargs)

    def print_role_header(self, console: Console) -> None:
        print_role_header(
            console,
            bot_name=self.bot_name,
            bot_icon=self.bot_icon,
            mode=self.role_header_mode,
            accent_color=self.accent_color,
            as_box=self.turn_box,
        )

    def print_user_separator(self, console: Console, width: int = 60) -> None:
        print_user_separator(console, width=width, enabled=self.user_separator)

    def print_turn_gap(self, console: Console) -> None:
        print_turn_gap(console, gap=self.gap_after_turn)

    def print_user_box(self, console: Console) -> None:
        """Print the user-turn box header (Camada 5).

        Companion to :meth:`print_role_header` when ``turn_box=True``.
        No-op when ``turn_box=False`` (legacy text "You:" prompt).
        """
        if not self.turn_box:
            return
        console.print(
            user_box(
                user_name=self.user_name,
                user_icon=self.user_icon,
                accent_color=self.user_accent_color,
            )
        )

    def print_input_gap(self, console: Console) -> None:
        """Print blank lines before the user input prompt (Camada 5)."""
        for line in input_gap_lines(self.gap_before_input):
            console.print(line)

    def apply_margin(self, console: Console) -> Console:
        """Return a child Console with reduced width (simulates horizontal margin).

        Rich's ``Console`` doesn't accept ``pad_left``/``pad_right`` at
        construction time, so we shrink the rendered ``width`` instead.
        Callers should print through this child console to get indented
        content; the ``margin_x`` value is honored on both sides.

        Example::

            child = self.apply_margin(parent_console)
            child.print("[bold]Hello[/bold]")
        """
        left, right = margin_padding(self.margin_x)
        new_width = max(MIN_OUTPUT_WIDTH, console.width - left - right)
        try:
            return Console(
                file=console.file,
                width=new_width,
                color_system=console.color_system,
                force_terminal=console.is_terminal,
            )
        except Exception:
            return console