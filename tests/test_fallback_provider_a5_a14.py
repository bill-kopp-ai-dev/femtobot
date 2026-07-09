"""FallbackProvider primary-error log + arrearage triggers (A5, A14).

A5 (REFACTOR_PLAN.md Lote A): when the primary provider returns an error
that triggers a fallback attempt, the wrapper now logs the primary error
*before* trying the fallback.  Historically only the "trying next
fallback" message survived, leaving an on-call engineer with no way to
see what went wrong on the primary.  The wrapper also exposes an
``on_primary_error`` callback for tests / metrics.

A14: the token set now recognizes arrearage / 欠费 / payment_required
markers so a primary key in arrears falls back to a healthy sibling
model (the user finishes their turn) instead of erroring out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from femtobot.providers.base import LLMProvider, LLMResponse
from femtobot.providers.fallback_provider import FallbackProvider

pytestmark = [pytest.mark.security, pytest.mark.asyncio]


@dataclass
class _PresetStub:
    """Minimal fallback preset stub with the fields FallbackProvider reads."""

    model: str
    max_tokens: int | None = None
    temperature: float | None = None
    reasoning_effort: str | None = None


class _FakeProvider(LLMProvider):
    """Minimal provider stub for FallbackProvider tests."""

    def __init__(self, response: LLMResponse) -> None:
        self._response = response

    async def chat(self, **kwargs: Any) -> LLMResponse:
        return self._response

    async def chat_stream(self, **kwargs: Any) -> LLMResponse:
        return self._response

    def get_default_model(self) -> str:
        return "fake-model"

    @property
    def generation(self) -> None:  # type: ignore[override]
        return None

    @generation.setter
    def generation(self, value) -> None:  # type: ignore[override]
        pass


def _err(content: str, *, kind: str = "server_error", status: int = 500) -> LLMResponse:
    return LLMResponse(
        content=content,
        finish_reason="error",
        error_kind=kind,
        error_status_code=status,
    )


def _ok(content: str = "ok") -> LLMResponse:
    return LLMResponse(content=content, finish_reason="stop")


async def test_primary_error_logged_before_fallback() -> None:
    """A5: a fallbackable error is logged before the fallback is attempted."""
    primary_response = _err("rate limit exceeded", kind="rate_limit", status=429)
    primary = _FakeProvider(primary_response)
    fallback = _FakeProvider(_ok("from fallback"))
    observed: list[LLMResponse] = []

    fb = FallbackProvider(
        primary=primary,
        fallback_presets=[_PresetStub(model="fb-1")],
        provider_factory=lambda _p: fallback,
        on_primary_error=observed.append,
    )

    await fb.chat(model="primary-1")

    assert len(observed) == 1, "primary error should be reported exactly once"
    assert observed[0].error_kind == "rate_limit"


async def test_non_fallbackable_error_does_not_invoke_fallback() -> None:
    """A5: a 400 / 401 / 403 (non-fallbackable) is reported but does NOT fall back."""
    primary = _FakeProvider(_err("bad request", kind="invalid_request", status=400))
    fallback = _FakeProvider(_ok("never called"))
    observed: list[LLMResponse] = []

    fb = FallbackProvider(
        primary=primary,
        fallback_presets=[_PresetStub(model="fb-1")],
        provider_factory=lambda _p: fallback,
        on_primary_error=observed.append,
    )

    resp = await fb.chat(model="primary-1")
    assert resp.finish_reason == "error"

    # The on_primary_error hook is still called (so the operator can see the
    # non-fallbackable error in the logs), but the fallback is NOT attempted.
    assert len(observed) == 1
    assert observed[0].error_kind == "invalid_request"
    assert resp.content == "bad request", "fallback must not have been attempted"


async def test_arrearage_triggers_fallback() -> None:
    """A14: 'arrearage' in the error content triggers the fallback path."""
    primary = _FakeProvider(_err("HTTP 402: arrearage - please top up", status=402))
    fallback = _FakeProvider(_ok("from fallback"))
    fb = FallbackProvider(
        primary=primary,
        fallback_presets=[_PresetStub(model="fb-1")],
        provider_factory=lambda _p: fallback,
    )

    resp = await fb.chat(model="primary-1")
    assert resp.finish_reason == "stop"
    assert resp.content == "from fallback"


async def test_chinese_arrearage_triggers_fallback() -> None:
    """A14: '欠费' (arrearage in Chinese) triggers the fallback path."""
    primary = _FakeProvider(_err("账户欠费，请充值后重试", kind="rate_limit", status=429))
    fallback = _FakeProvider(_ok("from fallback"))
    fb = FallbackProvider(
        primary=primary,
        fallback_presets=[_PresetStub(model="fb-1")],
        provider_factory=lambda _p: fallback,
    )

    resp = await fb.chat(model="primary-1")
    assert resp.content == "from fallback"


async def test_payment_required_triggers_fallback() -> None:
    """A14: 'payment_required' (lowercase) is recognized as a fallback token."""
    primary = _FakeProvider(
        _err(
            "payment_required: please update billing",
            kind="server_error",
            status=500,
        )
    )
    fallback = _FakeProvider(_ok("from fallback"))
    fb = FallbackProvider(
        primary=primary,
        fallback_presets=[_PresetStub(model="fb-1")],
        provider_factory=lambda _p: fallback,
    )

    resp = await fb.chat(model="primary-1")
    assert resp.content == "from fallback"


async def test_on_primary_error_exception_is_swallowed() -> None:
    """A5: a buggy observer must not break the fallback path."""

    def _boom(_resp: LLMResponse) -> None:
        raise RuntimeError("observer is broken")

    primary = _FakeProvider(_err("server_error", kind="server_error", status=500))
    fallback = _FakeProvider(_ok("from fallback"))
    fb = FallbackProvider(
        primary=primary,
        fallback_presets=[_PresetStub(model="fb-1")],
        provider_factory=lambda _p: fallback,
        on_primary_error=_boom,
    )

    resp = await fb.chat(model="primary-1")
    assert resp.content == "from fallback"
