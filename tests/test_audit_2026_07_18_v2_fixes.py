"""Regression tests for the 2026-07-18 second-pass audit fixes.

Each test exercises one of the bugs reported in
``femtobot-bugs-found-2.md``.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from femtobot.agent.output import FemtobotOutput
from femtobot.channels.websocket import _is_localhost
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Bug HIGH #1: FemtobotAgent._build_model must raise a clean error when
# the OpenAI-compat provider has no credentials.
# ---------------------------------------------------------------------------


def test_build_model_raises_actionable_when_no_credentials() -> None:
    """When the chosen provider has no api_key and no api_base,
    _build_model must raise a RuntimeError pointing at the right env vars,
    not the generic OpenAI SDK exception."""
    from femtobot.agent.femtobot_agent import _build_model

    cfg = MagicMock()
    cfg.agents.defaults.provider = "openai"
    cfg.agents.defaults.model = "gpt-4o"
    # provider with NO api_key and NO api_base
    openai_cfg = MagicMock()
    openai_cfg.api_key = None
    openai_cfg.api_base = None
    cfg.providers.openai = openai_cfg

    # _resolve_provider_name may pick a different one — force it.
    cfg.agents.defaults.provider = "openai"
    with pytest.raises(RuntimeError, match="api_key|api_base"):
        _build_model(cfg)


# ---------------------------------------------------------------------------
# Bug HIGH #2: FemtobotOutput.no_internal_leakage must NOT block legitimate
# prose mentions of AGENTS.md / SOUL.md / HEARTBEAT.md / AWARENESS.md.
# ---------------------------------------------------------------------------


def test_internal_leakage_accepts_legitimate_prose_mention() -> None:
    """A plain English sentence mentioning AGENTS.md is allowed."""
    out = FemtobotOutput(final_message="Your personalized notes live in AGENTS.md.")
    assert out.final_message  # did not raise


def test_internal_leakage_accepts_lowercase_mention() -> None:
    """Lowercase mentions are also allowed (regex is case-insensitive but
    only matches path-like patterns)."""
    out = FemtobotOutput(final_message="edit agents.md to customize your identity.")
    assert out.final_message


def test_internal_leakage_accepts_brand_explanation() -> None:
    """Sentences explaining the product are allowed."""
    out = FemtobotOutput(
        final_message="femtobot uses AGENTS.md for identity and SOUL.md for persona."
    )
    assert out.final_message


def test_internal_leakage_rejects_path_like_reference() -> None:
    """Path-like references (preceded by '/') ARE blocked."""
    with pytest.raises(ValidationError):
        FemtobotOutput(final_message="read /home/user/.femtobot/agents.md for details")


def test_internal_leakage_rejects_relative_path() -> None:
    """Relative path references are blocked."""
    with pytest.raises(ValidationError):
        FemtobotOutput(final_message="see ./AGENTS.md for context")


# ---------------------------------------------------------------------------
# Bug MEDIUM: _NATIVE_PROVIDERS is now actually used by _build_model
# ---------------------------------------------------------------------------


def test_native_providers_is_used_in_build_model() -> None:
    """The _NATIVE_PROVIDERS frozenset must be referenced by _build_model,
    not just defined and forgotten."""
    import inspect

    from femtobot.agent.femtobot_agent import _NATIVE_PROVIDERS, _build_model

    src = inspect.getsource(_build_model)
    assert "_NATIVE_PROVIDERS" in src or "_NON_OPENAI_NATIVE" in src
    assert isinstance(_NATIVE_PROVIDERS, frozenset)
    assert "openai" in _NATIVE_PROVIDERS
    assert "anthropic" in _NATIVE_PROVIDERS
    assert "bedrock" in _NATIVE_PROVIDERS
    assert "gemini" in _NATIVE_PROVIDERS


# ---------------------------------------------------------------------------
# Bug MEDIUM: combined_toolset logs (instead of swallowing) toolset failures
# ---------------------------------------------------------------------------


def test_combined_toolset_logs_on_failure() -> None:
    """When a toolset module raises during construction,
    combined_toolset must log a warning — not silently skip."""
    from femtobot.agent.toolsets import _combined

    captured: list[str] = []

    def _sink(message) -> None:
        record = message.record
        captured.append(str(record["message"]) if "message" in record else str(record))

    import loguru

    handler_id = loguru.logger.add(_sink, level="WARNING")
    try:
        def _exploding():
            raise RuntimeError("boom")

        original = _combined._available_toolsets
        _combined._available_toolsets = lambda: [_exploding]  # type: ignore[assignment]
        try:
            tools = _combined.combined_toolset()
        finally:
            _combined._available_toolsets = original  # type: ignore[assignment]
    finally:
        loguru.logger.remove(handler_id)
    # The failing toolset is dropped but a warning is logged.
    assert tools == []
    assert any("boom" in msg for msg in captured), (
        f"expected a warning containing 'boom'; got {captured!r}"
    )


# ---------------------------------------------------------------------------
# Bug LOW: _is_localhost uses ipaddress.is_loopback (defends against
# strings like "127.0.0.1.attacker.com").
# ---------------------------------------------------------------------------


def test_is_localhost_rejects_prefix_attack() -> None:
    """A string starting with '127.' that is not a valid IP must be rejected."""
    conn = MagicMock()
    conn.remote_address = ("127.0.0.1.attacker.com", 12345)
    assert _is_localhost(conn) is False


def test_is_localhost_accepts_127_subnet() -> None:
    conn = MagicMock()
    conn.remote_address = ("127.0.0.5", 12345)
    assert _is_localhost(conn) is True


def test_is_localhost_rejects_empty_string() -> None:
    conn = MagicMock()
    conn.remote_address = ("", 12345)
    assert _is_localhost(conn) is False


# ---------------------------------------------------------------------------
# Bug MEDIUM: build_system_prompt returns the minimal fallback when
# ContextBuilder fails or yields no system message.
# ---------------------------------------------------------------------------


def test_build_system_prompt_falls_back_on_import_failure(
    monkeypatch,
) -> None:
    """If ContextBuilder fails to import, build_system_prompt returns
    a non-empty minimal prompt rather than the empty string."""
    from femtobot.agent import femtobot_agent

    # Simulate ImportError on the lazy import.
    import builtins

    original_import = builtins.__import__

    def _failing_import(name, *args, **kwargs):
        if "agent.context" in name or "bus.events" in name:
            raise ImportError(f"simulated: cannot import {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _failing_import)

    cfg = MagicMock()
    prompt = femtobot_agent.build_system_prompt(cfg, MagicMock())
    assert prompt
    assert "Femtobot" in prompt  # the minimal fallback mentions the brand


def test_build_system_prompt_returns_nonempty_for_fresh_config(
    monkeypatch, tmp_path,
) -> None:
    """A brand-new workspace (no AGENTS.md / SOUL.md) must still produce
    a non-empty system prompt thanks to the minimal fallback.

    We patch ``femtobot.agent.context.ContextBuilder`` to return no
    system message so we exercise the fallback path without depending
    on the rest of ContextBuilder's machinery (which has its own bugs
    out of scope for this audit pass)."""
    from femtobot.agent import femtobot_agent

    class _StubBuilder:
        def __init__(self, *a, **kw) -> None:
            pass

        def build_messages(self, *a, **kw) -> list[dict]:
            return []

    # ``ContextBuilder`` is imported lazily inside build_system_prompt
    # via ``from femtobot.agent.context import ContextBuilder``, so we
    # patch the source module attribute to make the local import
    # resolve to our stub.
    import femtobot.agent.context as _ctx_module

    monkeypatch.setattr(_ctx_module, "ContextBuilder", _StubBuilder)

    cfg = MagicMock()
    prompt = femtobot_agent.build_system_prompt(cfg, tmp_path)
    assert isinstance(prompt, str)
    assert prompt.strip(), (
        "build_system_prompt returned empty for a fresh workspace — "
        "the minimal fallback was not engaged"
    )
