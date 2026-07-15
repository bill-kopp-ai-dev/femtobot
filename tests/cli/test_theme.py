"""Tests for the theme module."""

from __future__ import annotations

import pytest

from femtobot.cli.theme import (
    THEMES,
    get_theme,
    is_valid_theme,
    list_themes,
)


def test_themes_count_matches_canonical_presets() -> None:
    assert len(THEMES) == 4
    assert "terracotta-claude" in THEMES
    assert "solarized-light" in THEMES
    assert "cyber-dark" in THEMES
    assert "monochrome" in THEMES


def test_theme_names_canonical_order() -> None:
    """Names follow the order they appear in ``THEMES``."""
    assert list_themes() == list(THEMES.keys())


def test_get_theme_unknown_falls_back_to_default() -> None:
    """Unknown theme names silently return the safe default."""
    fallback = get_theme("does-not-exist")
    assert fallback.name == "terracotta-claude"


def test_get_theme_known() -> None:
    assert get_theme("monochrome").name == "monochrome"


def test_cli_theme_is_frozen() -> None:
    """Mutating a theme must raise ``FrozenInstanceError`` (or ``AttributeError``)."""
    t = get_theme("terracotta-claude")
    with pytest.raises((AttributeError, TypeError)):
        t.primary = "#000000"  # type: ignore[misc]


def test_is_valid_theme() -> None:
    assert is_valid_theme("terracotta-claude") is True
    assert is_valid_theme("bogus-theme") is False


# ---------------------------------------------------------------------------
# v0.1.0-ui.0+ — parity tokens (T2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("theme_name", list(THEMES))
def test_parity_tokens_are_set_for_every_theme(theme_name: str) -> None:
    """Every theme provides a non-empty welcome_border, permission_accent
    and tool_card_border so the parity widgets never render with empty
    color strings (Rich would silently drop the style)."""
    t = THEMES[theme_name]
    assert t.welcome_border, f"{theme_name} missing welcome_border"
    assert t.permission_accent, f"{theme_name} missing permission_accent"
    assert t.tool_card_border, f"{theme_name} missing tool_card_border"


def test_terracotta_theme_welcome_border_matches_primary() -> None:
    """The default theme reuses ``primary`` for the welcome border so
    the parity welcome card visually rhymes with the existing role bar."""
    t = get_theme("terracotta-claude")
    assert t.welcome_border == t.primary


def test_terracotta_theme_permission_accent_matches_perm_border() -> None:
    """Reuse the existing ``perm_border`` token so the permission prompt
    number-highlight stays consistent with the v0.0.x Femtobot accent."""
    t = get_theme("terracotta-claude")
    assert t.permission_accent == t.perm_border
