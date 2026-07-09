"""Provider config tests for A11 (extraQuery) and A12 (Anthropic tool IDs)."""

from __future__ import annotations

import pytest

from femtobot.providers.openai_compat_provider import (
    _append_query_params,
    _sanitize_anthropic_tool_id,
)

pytestmark = pytest.mark.security


def test_append_query_params_basic() -> None:
    """A11: extraQuery values are appended to a bare URL."""
    assert (
        _append_query_params("https://api.example.com", {"api-version": "2024-01-01"})
        == "https://api.example.com?api-version=2024-01-01"
    )


def test_append_query_params_preserves_existing() -> None:
    """A11: existing query parameters in apiBase win on collision (A11)."""
    merged = _append_query_params(
        "https://api.example.com?existing=1",
        {"api-version": "2024-01-01"},
    )
    assert "existing=1" in merged
    assert "api-version=2024-01-01" in merged


def test_append_query_params_overrides_when_key_collides() -> None:
    """A11: the explicit apiBase value wins on key collision (A11)."""
    merged = _append_query_params(
        "https://api.example.com?api-version=keep-me",
        {"api-version": "2024-01-01"},
    )
    assert "keep-me" in merged
    assert "2024-01-01" not in merged


def test_append_query_params_no_params_noop() -> None:
    """A11: an empty params dict is a no-op (A11)."""
    assert _append_query_params("https://api.example.com", {}) == "https://api.example.com"


def test_append_query_params_escapes_special_chars() -> None:
    """A11: special characters in values are URL-escaped (A11)."""
    merged = _append_query_params(
        "https://api.example.com",
        {"key": "value with space & special=chars"},
    )
    assert "value" in merged
    # Either "+" or "%20" is acceptable for spaces; the important thing is
    # that the raw space is not preserved.
    assert " " not in merged.split("?", 1)[1]


def test_sanitize_anthropic_id_passthrough() -> None:
    """A12: a well-formed ID is returned unchanged."""
    assert _sanitize_anthropic_tool_id("toolu_vrtok_01ABC") == "toolu_vrtok_01ABC"


def test_sanitize_anthropic_id_replaces_special_chars() -> None:
    """A12: characters outside ``[A-Za-z0-9_-]`` are replaced with ``_`` (A12)."""
    sanitized = _sanitize_anthropic_tool_id("tool use 1/2")
    assert " " not in sanitized
    assert "/" not in sanitized
    # The pattern now matches Anthropic's whitelist.
    import re

    assert re.match(r"^[a-zA-Z0-9_-]{1,64}$", sanitized)


def test_sanitize_anthropic_id_handles_unicode() -> None:
    """A12: Unicode characters that don't fit the pattern are stripped (A12)."""
    sanitized = _sanitize_anthropic_tool_id("café_☕")
    import re

    assert re.match(r"^[a-zA-Z0-9_-]{1,64}$", sanitized)


def test_sanitize_anthropic_id_truncates_long() -> None:
    """A12: IDs longer than 64 chars are truncated."""
    long_id = "a" * 200
    sanitized = _sanitize_anthropic_tool_id(long_id)
    assert len(sanitized) <= 64


def test_sanitize_anthropic_id_empty_uses_random() -> None:
    """A12: empty input gets a fresh short ID (not a deterministic hash)."""
    import re

    sanitized = _sanitize_anthropic_tool_id("")
    assert re.match(r"^[a-zA-Z0-9_-]{1,64}$", sanitized)
