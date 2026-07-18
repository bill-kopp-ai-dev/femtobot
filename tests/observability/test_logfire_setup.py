"""Tests for ``femtobot/observability/logfire_setup.py``.

Phase 6 — exercise the configure/instrument surface without sending
anything to Logfire. Logfire is off by default in tests; we explicitly
force ``send_to_logfire=False`` to keep CI hermetic.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture(autouse=True)
def _disable_logfire_during_tests(monkeypatch):
    """Force Logfire off in tests unless explicitly enabled."""
    monkeypatch.setenv("FEMTOBOT_LOGFIRE_SEND", "no")
    # Reset module-level idempotency flags so each test sees a fresh setup.
    from femtobot.observability import logfire_setup

    logfire_setup._CONFIGURED = False
    logfire_setup._INSTRUMENTED = False
    logfire_setup._HTTPX_INSTRUMENTED = False
    yield


def test_configure_disabled_in_tests() -> None:
    """Calling ``configure()`` with FEMTOBOT_LOGFIRE_SEND=no must not raise."""
    from femtobot.observability import logfire_setup

    logfire_setup.configure()
    # The second call is a no-op (idempotent).
    logfire_setup.configure()
    assert logfire_setup._CONFIGURED is True


def test_resolve_send_mode_from_env(monkeypatch) -> None:
    """Env precedence: FEMTOBOT_LOGFIRE_SEND > FEMTOBOT_LOGFIRE > default."""
    from femtobot.observability import logfire_setup

    monkeypatch.delenv("FEMTOBOT_LOGFIRE_SEND", raising=False)
    monkeypatch.delenv("FEMTOBOT_LOGFIRE", raising=False)
    assert logfire_setup._resolve_send_mode() == "if-token-present"

    monkeypatch.setenv("FEMTOBOT_LOGFIRE", "1")
    assert logfire_setup._resolve_send_mode() == "yes"

    monkeypatch.setenv("FEMTOBOT_LOGFIRE_SEND", "no")
    assert logfire_setup._resolve_send_mode() == "no"

    monkeypatch.setenv("FEMTOBOT_LOGFIRE_SEND", "if-token-present")
    assert logfire_setup._resolve_send_mode() == "if-token-present"


def test_instrument_httpx_off_by_default(monkeypatch) -> None:
    """httpx instrumentation is opt-in; no env var means no-op."""
    from femtobot.observability import logfire_setup

    monkeypatch.delenv("FEMTOBOT_LOGFIRE_HTTPX", raising=False)
    logfire_setup.instrument_httpx()
    assert logfire_setup._HTTPX_INSTRUMENTED is False


def test_instrument_httpx_enabled_via_env(monkeypatch) -> None:
    """Setting ``FEMTOBOT_LOGFIRE_HTTPX=1`` flips the instrumented flag."""
    from femtobot.observability import logfire_setup

    monkeypatch.setenv("FEMTOBOT_LOGFIRE_HTTPX", "1")
    logfire_setup.instrument_httpx()
    assert logfire_setup._HTTPX_INSTRUMENTED is True


def test_module_reimportable() -> None:
    """The module re-imports cleanly without side effects on config."""
    mod = importlib.import_module("femtobot.observability.logfire_setup")
    assert "configure" in mod.__all__
    assert "instrument_pydantic_ai" in mod.__all__
    assert "instrument_httpx" in mod.__all__
