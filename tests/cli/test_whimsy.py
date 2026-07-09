"""Tests for the whimsy module (verb pool + spinner styles)."""

from __future__ import annotations

from femtobot.cli.whimsy import (
    DEFAULT_VERBS,
    SPINNER_STYLES,
    pick_spinner,
    pick_verb,
    resolve_spinner,
    rotate_verb,
)


def test_default_verbs_pool_minimum_size() -> None:
    """Verb pool must have at least 40 entries (config default)."""
    assert len(DEFAULT_VERBS) >= 40


def test_pick_verb_returns_member() -> None:
    v = pick_verb(seed=42)
    assert v in DEFAULT_VERBS


def test_pick_verb_deterministic_with_seed() -> None:
    assert pick_verb(seed=123) == pick_verb(seed=123)
    assert pick_verb(seed=1) != pick_verb(seed=2)


def test_pick_spinner_returns_known_style() -> None:
    s = pick_spinner(seed=7)
    assert s in SPINNER_STYLES


def test_pick_spinner_deterministic() -> None:
    assert pick_spinner(seed=1) == pick_spinner(seed=1)
    assert pick_spinner(seed=1) != pick_spinner(seed=2)


def test_resolve_spinner_auto_sentinel() -> None:
    """``None`` and ``"auto"`` should both map to a real spinner."""
    assert resolve_spinner(None, seed=1) in SPINNER_STYLES
    assert resolve_spinner("auto", seed=2) in SPINNER_STYLES


def test_resolve_spinner_passthrough() -> None:
    """Explicit styles pass through unchanged."""
    assert resolve_spinner("dots") == "dots"
    assert resolve_spinner("line") == "line"


def test_rotate_verb_avoids_used() -> None:
    """If the pool has 40 entries and we use 39, the next pick must be the missing one."""
    used = list(DEFAULT_VERBS)[:39]
    chosen = rotate_verb(used, seed=99)
    assert chosen not in used
    assert chosen in DEFAULT_VERBS


def test_rotate_verb_fallback_when_exhausted() -> None:
    """If all verbs are used, fall back to a random pick."""
    chosen = rotate_verb(DEFAULT_VERBS, seed=42)
    assert chosen in DEFAULT_VERBS  # any verb is fine
