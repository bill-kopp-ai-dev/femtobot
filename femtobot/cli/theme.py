"""Color themes for the Femtobot CLI.

Each theme is a frozen dataclass mapping semantic roles to color strings
(hex, ANSI names, or names understood by Rich / prompt_toolkit). Four
presets are provided.

Camada 1 (1.6) do ``FEMTOBOT_CLI_REFACTOR_PLAN.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class CliTheme:
    """Color tokens for CLI rendering. Strings are passed to Rich / prompt_toolkit."""

    name: str
    primary: str        # Thinking, assistant header
    success: str        # Done markers, green checkmarks
    warning: str        # Cautions
    error: str          # Errors
    user_input_bg: str  # Background of user message
    tool_border: str    # Tool call border
    perm_border: str    # Permission dialog
    bg_input: str       # Dashed border accent (used by input border if any)
    accent: str = "cyan"  # Generic accent (logo, prompt label)
    # v0.1.0-ui.0+ — UI parity tokens (Claude Code v2.1.x aesthetic).
    # All themes provide sensible defaults so the parity widgets render
    # with the existing palette — no theme surgery needed.
    welcome_border: str = ""  # Welcome card + What's new box border
    permission_accent: str = ""  # Permission prompt option highlight
    tool_card_border: str = ""  # Tool call card border (collapsed/expanded)


THEMES: Mapping[str, CliTheme] = {
    "terracotta-claude": CliTheme(
        name="terracotta-claude",
        primary="#d77757",
        success="#4eba65",
        warning="#ffc107",
        error="#ff6b80",
        user_input_bg="grey23",
        tool_border="#fd5db1",
        perm_border="#b1b9f9",
        bg_input="#888888",
        accent="#d77757",
        welcome_border="#d77757",
        permission_accent="#b1b9f9",
        tool_card_border="#fd5db1",
    ),
    "solarized-light": CliTheme(
        name="solarized-light",
        primary="#268bd2",
        success="#859900",
        warning="#b58900",
        error="#dc322f",
        user_input_bg="grey93",
        tool_border="#cb4b16",
        perm_border="#6c71c4",
        bg_input="#93a1a1",
        accent="#268bd2",
        welcome_border="#268bd2",
        permission_accent="#6c71c4",
        tool_card_border="#cb4b16",
    ),
    "cyber-dark": CliTheme(
        name="cyber-dark",
        primary="#00ffff",
        success="#39ff14",
        warning="#ffaa00",
        error="#ff3860",
        user_input_bg="grey15",
        tool_border="#ff00ff",
        perm_border="#bcbcff",
        bg_input="#7f7f7f",
        accent="#00ffff",
        welcome_border="#00ffff",
        permission_accent="#bcbcff",
        tool_card_border="#ff00ff",
    ),
    "monochrome": CliTheme(
        name="monochrome",
        primary="#d0d0d0",
        success="#a0a0a0",
        warning="#b0b0b0",
        error="#909090",
        user_input_bg="grey23",
        tool_border="#808080",
        perm_border="#a0a0a0",
        bg_input="#707070",
        accent="#d0d0d0",
        welcome_border="#d0d0d0",
        permission_accent="#a0a0a0",
        tool_card_border="#808080",
    ),
}


THEME_NAMES: tuple[str, ...] = tuple(THEMES.keys())


def get_theme(name: str) -> CliTheme:
    """Resolve a theme by name, falling back to 'terracotta-claude' for safety."""
    return THEMES.get(name) or THEMES["terracotta-claude"]


def list_themes() -> list[str]:
    """All available theme names in canonical order."""
    return list(THEME_NAMES)


def is_valid_theme(name: str) -> bool:
    """Whether ``name`` is a known theme."""
    return name in THEMES
