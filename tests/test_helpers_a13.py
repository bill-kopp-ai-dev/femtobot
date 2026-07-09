"""Image placeholder privacy tests (A13).

A13 (REFACTOR_PLAN.md Lote A): ``image_placeholder_text`` no longer
embeds the local filesystem path in the user-visible string.  The path
can leak into prompt transcripts (and from there into logs / cloud
upstream calls) — replacing it with ``[image omitted]`` keeps the
replay transcript short and privacy-safe.
"""

from __future__ import annotations

import pytest

from femtobot.utils.helpers import image_placeholder_text

pytestmark = pytest.mark.security


def test_image_placeholder_omits_path() -> None:
    """A13: a real path is replaced with a privacy-safe token."""
    out = image_placeholder_text("/home/user/secret/photo.png")
    assert out == "[image omitted]"
    assert "secret" not in out
    assert "photo.png" not in out
    assert "/home/user" not in out


def test_image_placeholder_empty_returns_empty_token() -> None:
    """A13: an empty path still falls back to the default empty token."""
    assert image_placeholder_text(None) == "[image]"
    assert image_placeholder_text("") == "[image]"


def test_image_placeholder_custom_empty_token() -> None:
    """A13: callers can pass a custom empty token."""
    assert image_placeholder_text(None, empty="(no image)") == "(no image)"


def test_image_placeholder_does_not_leak_windows_paths() -> None:
    """A13: Windows-style paths are also scrubbed (A13)."""
    out = image_placeholder_text("C:\\Users\\admin\\Pictures\\cat.jpg")
    assert "admin" not in out
    assert "cat.jpg" not in out
    assert out == "[image omitted]"
