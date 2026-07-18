"""Regression tests for audit 2026-07-18 v5 (/btw provider wiring).

The /btw side-question handler was looking up a non-existent
``provider.generate`` method, silently returning ``None`` whenever the
active provider exposed the real ``chat_with_retry`` / ``chat``
entry points. The fallback message "Could not process the question.
Is the model connected?" surfaced to the user — confusing, because
the model was actually connected.

Fix: ``run_btw`` now resolves ``chat_with_retry`` (or ``chat`` as a
fallback) on the provider, awaits the result, and extracts the text
via ``response.content``. The exception path also surfaces the
underlying exception type/message instead of a generic notice.

These tests pin down the new wiring without spinning up the real
provider stack.
"""

from __future__ import annotations

from typing import Any

import pytest

from femtobot.cli.btw import run_btw


class FakeResponse:
    """Stand-in for ``providers.LLMResponse``."""

    def __init__(self, content: Any) -> None:
        self.content = content


class ChatWithRetryProvider:
    """Provider exposing the canonical ``chat_with_retry`` entry point."""

    def __init__(self, response: Any) -> None:
        self._response = response

    async def chat_with_retry(
        self, *, messages: list, tools: Any = None
    ) -> Any:
        return self._response


class ChatOnlyProvider:
    """Provider that only exposes ``chat`` (older fallback path)."""

    def __init__(self, response: Any) -> None:
        self._response = response

    async def chat(self, *, messages: list, tools: Any = None) -> Any:
        return self._response


class BareProvider:
    """Provider with neither chat_with_retry nor chat."""

    pass


class FakeLoop:
    def __init__(self, provider: Any) -> None:
        self.provider = provider
        self.sessions = None


# ---------------------------------------------------------------------------
# Real provider wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_btw_uses_chat_with_retry_when_available() -> None:
    """The canonical path: provider.chat_with_retry is awaited."""
    provider = ChatWithRetryProvider(FakeResponse("42"))
    loop = FakeLoop(provider)
    result = await run_btw(loop, "how much is 6 * 7?", "k")
    assert result is not None
    assert result.content == "42"
    assert result.metadata.get("_btw") is True


@pytest.mark.asyncio
async def test_run_btw_extracts_response_content_attribute() -> None:
    """``run_btw`` must read ``response.content`` (LLMResponse shape)."""
    provider = ChatWithRetryProvider(FakeResponse("explicit content"))
    loop = FakeLoop(provider)
    result = await run_btw(loop, "q", "k")
    assert result is not None
    assert result.content == "explicit content"


@pytest.mark.asyncio
async def test_run_btw_returns_none_when_provider_missing_methods() -> None:
    """A provider with neither chat_with_retry nor chat → graceful None."""
    loop = FakeLoop(BareProvider())
    result = await run_btw(loop, "q", "k")
    assert result is None


@pytest.mark.asyncio
async def test_run_btw_handles_empty_content() -> None:
    """Empty / None content → result.content is empty string."""
    for raw in (None, ""):
        provider = ChatWithRetryProvider(FakeResponse(raw))
        loop = FakeLoop(provider)
        result = await run_btw(loop, "q", "k")
        assert result is not None
        assert result.content == ""


# ---------------------------------------------------------------------------
# Error surface
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_btw_surfaces_exception_type_and_message() -> None:
    """An exception during chat_with_retry must surface its type and
    message so the user can self-diagnose instead of seeing a
    generic notice."""

    class BoomProvider:
        async def chat_with_retry(self, **kw: Any) -> Any:
            raise ConnectionError("api unreachable")

    loop = FakeLoop(BoomProvider())
    result = await run_btw(loop, "q", "k")
    assert result is not None
    assert "ConnectionError" in result.content
    assert "api unreachable" in result.content
    # The error reply is still tagged so the REPL knows it is a btw
    # message and not a regular turn.
    assert result.metadata.get("_btw") is True


@pytest.mark.asyncio
async def test_run_btw_elapsed_metadata_set_on_error() -> None:
    """Even the error path stamps ``_btw_elapsed_s`` for consistency."""

    class BoomProvider:
        async def chat_with_retry(self, **kw: Any) -> Any:
            raise RuntimeError("nope")

    loop = FakeLoop(BoomProvider())
    result = await run_btw(loop, "q", "k")
    assert result is not None
    assert "_btw_elapsed_s" in result.metadata
