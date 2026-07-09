"""Tests for B3 (real LLM usage forwarding).

B3 (REFACTOR_PLAN.md Lote B):
* ``Femtobot.run()`` populates ``RunResult.usage`` from the underlying
  ``LLMResponse.usage`` dict.
* ``_chat_completion_response`` in ``api/server.py`` normalizes the
  usage dict into the OpenAI-compatible response payload.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from femtobot.api.server import _chat_completion_response
from femtobot.femtobot import Femtobot

pytestmark = pytest.mark.durability


class _StubLoop:
    def __init__(self, usage: dict[str, int] | None) -> None:
        self._usage = usage or {}
        self._extra_hooks: list[Any] = []

    async def process_direct(
        self,
        message: str,
        *,
        session_key: str,
        **_kwargs: Any,
    ) -> Any:
        from femtobot.providers.base import LLMResponse

        return LLMResponse(
            content=f"echo: {message}",
            finish_reason="stop",
            usage=dict(self._usage),
        )


def _new_bot(usage: dict[str, int] | None) -> Femtobot:
    bot = Femtobot.__new__(Femtobot)  # type: ignore[call-arg]
    bot._loop = _StubLoop(usage)  # type: ignore[attr-defined]
    import weakref

    bot._sdk_locks = weakref.WeakValueDictionary()  # type: ignore[attr-defined]
    bot._sdk_locks_lock = asyncio.Lock()  # type: ignore[attr-defined]
    bot._lock_timeout_s = 0.0  # disable locking for test speed
    return bot


async def test_run_result_includes_usage() -> None:
    """B3: ``RunResult.usage`` is populated when the provider returns usage (B3)."""
    bot = _new_bot({"prompt_tokens": 17, "completion_tokens": 9, "total_tokens": 26})
    result = await bot.run("hi")
    assert result.usage == {"prompt_tokens": 17, "completion_tokens": 9, "total_tokens": 26}


async def test_run_result_usage_empty_when_provider_omits() -> None:
    """B3: ``RunResult.usage`` is empty when the provider returned no usage (B3)."""
    bot = _new_bot(None)
    result = await bot.run("hi")
    # ``LLMResponse.usage`` defaults to an empty dict; ``Femtobot.run``
    # forwards it as-is.  The API layer distinguishes "no usage" from
    # "zero usage" via the dict's contents.
    assert result.usage == {}


def test_chat_completion_response_forwards_real_usage() -> None:
    """B3: real usage is forwarded into the OpenAI-compatible payload (B3)."""
    payload = _chat_completion_response(
        "ok",
        "model-x",
        usage={"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
    )
    assert payload["usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 4,
        "total_tokens": 16,
    }


def test_chat_completion_response_computes_total_when_missing() -> None:
    """B3: when ``total_tokens`` is omitted, it is summed from prompt + completion (B3)."""
    payload = _chat_completion_response(
        "ok",
        "model-x",
        usage={"prompt_tokens": 10, "completion_tokens": 5},
    )
    assert payload["usage"]["total_tokens"] == 15


def test_chat_completion_response_falls_back_to_zeros() -> None:
    """B3: backward-compat: usage=None returns the historical zero placeholder (B3)."""
    payload = _chat_completion_response("ok", "model-x")
    assert payload["usage"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
