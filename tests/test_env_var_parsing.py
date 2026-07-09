"""``FEMTOBOT_MAX_CONCURRENT_REQUESTS`` env var parsing tests (v0.0.9 H2).

Audit H2: the previous ``int(os.environ.get(...))`` crashed startup
with ``ValueError`` if the env var was set to a non-integer (e.g.
``"many"``).  We now fall back to the default and log a warning.

We pin:

* valid integer env vars are honored,
* non-integer env vars fall back to the default (3) with a
  warning logged,
* an unset env var uses the default,
* an env var of ``0`` or negative means unlimited (no
  semaphore), still works after the fix.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from femtobot.agent.loop import AgentLoop
from femtobot.bus.queue import MessageBus
from femtobot.providers.base import LLMProvider


class _StubProvider(LLMProvider):
    def get_default_model(self) -> str:
        return "stub-model"

    async def chat(self, *args, **kwargs):  # pragma: no cover - not used
        return None

    async def chat_stream(self, *args, **kwargs):  # pragma: no cover - not used
        yield None


def test_default_concurrency_gate_is_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H2: default (3) gives a present ``_concurrency_gate`` (H2 baseline)."""
    monkeypatch.delenv("FEMTOBOT_MAX_CONCURRENT_REQUESTS", raising=False)
    loop = AgentLoop(bus=MessageBus(), provider=_StubProvider(), workspace=tmp_path)
    assert loop._concurrency_gate is not None


def test_valid_integer_env_var_is_honored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H2: a valid integer env var is parsed correctly (H2)."""
    monkeypatch.setenv("FEMTOBOT_MAX_CONCURRENT_REQUESTS", "7")
    loop = AgentLoop(bus=MessageBus(), provider=_StubProvider(), workspace=tmp_path)
    # Semaphore(7) — verify the underlying counter.
    assert loop._concurrency_gate is not None
    # Semaphore's value isn't trivially readable, but a fresh
    # semaphore with no acquired slots has _value == 7.
    assert loop._concurrency_gate._value == 7  # type: ignore[attr-defined]


def test_invalid_env_var_falls_back_to_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H2: a non-integer env var falls back to 3 (H2)."""
    monkeypatch.setenv("FEMTOBOT_MAX_CONCURRENT_REQUESTS", "many")
    # Should not raise; should warn and use 3.
    loop = AgentLoop(bus=MessageBus(), provider=_StubProvider(), workspace=tmp_path)
    assert loop._concurrency_gate is not None
    assert loop._concurrency_gate._value == 3  # type: ignore[attr-defined]


def test_zero_env_var_means_unlimited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H2: ``0`` still means unlimited (H2 baseline preserved)."""
    monkeypatch.setenv("FEMTOBOT_MAX_CONCURRENT_REQUESTS", "0")
    loop = AgentLoop(bus=MessageBus(), provider=_StubProvider(), workspace=tmp_path)
    # ``_concurrency_gate`` is None when the value is <= 0.
    assert loop._concurrency_gate is None


def test_negative_env_var_means_unlimited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H2: a negative value also means unlimited (H2 baseline preserved)."""
    monkeypatch.setenv("FEMTOBOT_MAX_CONCURRENT_REQUESTS", "-1")
    loop = AgentLoop(bus=MessageBus(), provider=_StubProvider(), workspace=tmp_path)
    assert loop._concurrency_gate is None


def test_empty_string_env_var_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H2: an empty string falls back to 3 (H2)."""
    monkeypatch.setenv("FEMTOBOT_MAX_CONCURRENT_REQUESTS", "")
    loop = AgentLoop(bus=MessageBus(), provider=_StubProvider(), workspace=tmp_path)
    # ``int("")`` raises ``ValueError``; the fix catches that
    # and falls back to 3.
    assert loop._concurrency_gate is not None
    assert loop._concurrency_gate._value == 3  # type: ignore[attr-defined]
