"""Tests for the theme module."""

from __future__ import annotations

import pytest

from femtobot.cli.theme import (
    THEMES,
    THEME_NAMES,
    CliTheme,
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
