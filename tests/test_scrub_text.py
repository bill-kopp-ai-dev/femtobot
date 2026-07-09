"""``scrub_text`` tests (v0.0.8 third-pass audit B1, B2).

We pin:

* the helper redacts common credential shapes,
* the helper preserves the key/scheme prefix so logs stay
  informative,
* the helper is a no-op on text without secrets,
* the helper handles the empty / None cases without crashing.
"""

from __future__ import annotations

import pytest

from femtobot.utils.helpers import scrub_text

pytestmark = pytest.mark.security


def test_redacts_openai_style_key() -> None:
    """B1: OpenAI-style ``sk-...`` keys are replaced (B1)."""
    text = "user input: my key is sk-proj-abcdefghijklmnopqrstuvwxyz123"
    out = scrub_text(text)
    assert "sk-proj-" not in out
    assert "[REDACTED]" in out


def test_redacts_github_pat() -> None:
    """B1: GitHub PATs (``ghp_*``, ``gho_*``, etc.) are replaced (B1)."""
    pat = "ghp_" + "a" * 40
    out = scrub_text(f"token: {pat}")
    assert pat not in out
    assert "[REDACTED]" in out


def test_redacts_aws_access_key() -> None:
    """B1: AWS access keys (``AKIA*``) are replaced (B1)."""
    out = scrub_text("AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE")
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "[REDACTED]" in out


def test_redacts_authorization_header_but_keeps_scheme() -> None:
    """B1: Authorization headers keep the ``Bearer `` prefix (B1)."""
    token = "ghp_" + "a" * 40
    out = scrub_text(f"Authorization: Bearer {token}")
    assert "Authorization: Bearer [REDACTED]" in out
    assert token not in out


def test_redacts_generic_key_value_pair_but_keeps_key() -> None:
    """B1: ``api_key=…`` is replaced but the key prefix is kept (B1)."""
    out = scrub_text("api_key=supersecretvalue123")
    assert out == "api_key=[REDACTED]"


def test_redacts_password_pair() -> None:
    """B1: ``password=…`` is replaced (B1)."""
    out = scrub_text("password=hunter2hunter2")
    assert "hunter2hunter2" not in out
    assert out == "password=[REDACTED]"


def test_redacts_pem_block() -> None:
    """B1: PEM private-key headers are replaced (B1)."""
    out = scrub_text("-----BEGIN RSA PRIVATE KEY-----")
    assert "BEGIN" not in out
    assert "[REDACTED]" in out


def test_no_secret_text_unchanged() -> None:
    """B1: text without secrets is unchanged (B1)."""
    text = "this is a normal log line with no credentials"
    assert scrub_text(text) == text


def test_empty_string_returns_empty() -> None:
    """B1: empty input returns empty (B1)."""
    assert scrub_text("") == ""


def test_short_text_unchanged() -> None:
    """B1: short text that doesn't match any pattern is unchanged (B1)."""
    assert scrub_text("hi") == "hi"


def test_custom_placeholder() -> None:
    """B1: a custom ``placeholder`` is used (B1)."""
    out = scrub_text("password=hunter2hunter2", placeholder="<SECRET>")
    assert "<SECRET>" in out
    assert "[REDACTED]" not in out


def test_redacts_mixed_secrets() -> None:
    """B1: multiple secrets in the same text are all redacted (B1)."""
    text = (
        "config: api_key=abcdef12345678 "
        "and token: ghp_" + "a" * 40 + " "
        "and key sk-1234567890abcdefghij"
    )
    out = scrub_text(text)
    assert "abcdef12345678" not in out
    assert "ghp_" not in out
    assert "sk-1234567890abcdefghij" not in out
    # The "api_key=" prefix should still be present so the log is informative.
    assert "api_key=" in out
