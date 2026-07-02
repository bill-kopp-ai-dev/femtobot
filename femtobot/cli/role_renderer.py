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

DEFAULT_GAP = 1
MIN_GAP = 0
MAX_GAP = 3

DEFAULT_HEADER_MODE = "always"
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
) -> Text:
    """Build the per-turn role header rendered before an agent reply.

    Modes
    -----
    ``always``  — bold colored bar ``🤖 Femtobot ▌`` (default)
    ``minimal`` — emoji only, e.g. ``🤖`` (legacy Camada 1 behavior)
    ``off``     — empty renderable

    The bar uses ``accent_color`` so it picks up the active CliTheme.
    """
    normalized = _normalize_header_mode(mode)
    if normalized == "off":
        return Text("")
    if normalized == "minimal":
        return Text(f"{bot_icon} ", style="bold")
    # 'always' — full colored bar
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
# One-shot printer helpers
# ---------------------------------------------------------------------------


def print_role_header(
    console: Console,
    bot_name: str = "Femtobot",
    bot_icon: str = "🤖",
    *,
    mode: str = DEFAULT_HEADER_MODE,
    accent_color: str = "#d77757",
) -> None:
    """Print the role header to ``console`` (no-op when mode == 'off')."""
    header = role_header(
        bot_name=bot_name,
        bot_icon=bot_icon,
        mode=mode,
        accent_color=accent_color,
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
    """Coordinates role-header + user-separator + turn-gap.

    Reads the active ``agents.cli.*`` config (or accepts explicit kwargs).
    Use this from ``StreamRenderer`` so the REPL stays config-driven.
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
    ):
        self.gap_after_turn = _normalize_gap(gap_after_turn)
        self.role_header_mode = _normalize_header_mode(role_header_mode)
        self.user_separator = (
            True if user_separator is None else bool(user_separator)
        )
        self.accent_color = accent_color
        self.bot_name = bot_name
        self.bot_icon = bot_icon

    @classmethod
    def from_config(cls, config_obj: object, **overrides) -> "TurnSpacingRenderer":
        """Build a renderer from a Femtobot Config object.

        Reads ``agents.defaults.cli.gap_after_turn``,
        ``agents.defaults.cli.role_header``, and
        ``agents.defaults.cli.user_separator``. Any failure falls back to
        the module defaults (backward-compatible).
        """
        gap: int | None = None
        mode: str | None = None
        sep: bool | None = None
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
        except Exception:
            pass

        kwargs: dict = {
            "gap_after_turn": gap,
            "role_header_mode": mode,
            "user_separator": sep,
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
        )

    def print_user_separator(self, console: Console, width: int = 60) -> None:
        print_user_separator(console, width=width, enabled=self.user_separator)

    def print_turn_gap(self, console: Console) -> None:
        print_turn_gap(console, gap=self.gap_after_turn)