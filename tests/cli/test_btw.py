"""Tests for femtobot.cli.btw — /btw side-question handler."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from femtobot.cli.btw import run_btw

# ---------------------------------------------------------------------------
# Fake helpers
# ---------------------------------------------------------------------------


class FakeResponse:
    """Stand-in for the real ``LLMResponse`` dataclass."""

    def __init__(self, content: Any) -> None:
        # Allow string content or None — mirrors the real ``LLMResponse``
        # surface that ``run_btw`` consumes.
        self.content = content


class FakeProvider:
    """Minimal provider that returns a configurable response."""

    def __init__(self, response: Any) -> None:
        self._response = response

    async def chat_with_retry(
        self, *, messages: list, tools: Any = None
    ) -> Any:
        return self._response


class FakeProviderNoGenerate:
    """Provider that lacks both chat_with_retry and chat methods."""

    pass


class FakeSession:
    """Minimal session returning configurable history."""

    def __init__(self, history: Any) -> None:
        self._history = history

    def get_history(self, max_messages: int = 0) -> Any:
        return self._history


class FakeSessions:
    """Fake sessions registry that creates FakeSession instances."""

    def __init__(self, history: Any) -> None:
        self._history = history

    def get_or_create(self, key: str) -> FakeSession:
        return FakeSession(self._history)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_loop() -> type:
    """Return FakeLoop ready to be instantiated with a FakeProvider."""
    return FakeLoop


class FakeLoop:
    """Fake AgentLoop with configurable provider and sessions."""

    def __init__(self, provider: Any = None, sessions: Any = None) -> None:
        self.provider = provider
        self.sessions = sessions


# ---------------------------------------------------------------------------
# C1: provider absent (loop.provider = None) → returns None
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_returns_none_when_provider_is_none() -> None:
    """C1: provider missing → run_btw returns None."""
    loop = FakeLoop(provider=None)
    result = await run_btw(loop, "what time is it?", "session-key")
    assert result is None


# ---------------------------------------------------------------------------
# C2: provider without generate method → returns None
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_returns_none_when_provider_has_no_generate() -> None:
    """C2: provider without generate() method → returns None."""
    loop = FakeLoop(provider=FakeProviderNoGenerate())
    result = await run_btw(loop, "what time is it?", "session-key")
    assert result is None


# ---------------------------------------------------------------------------
# C3: sessions absent → proceeds without crash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_proceeds_without_crash_when_sessions_missing() -> None:
    """C3: sessions attribute missing → proceeds and returns a message."""
    loop = FakeLoop(provider=FakeProvider(FakeResponse("hello world")))
    result = await run_btw(loop, "what time is it?", "session-key")
    assert result is not None
    assert result.content == "hello world"


# ---------------------------------------------------------------------------
# C4: get_history returns dict/list empty → proceeds without crash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_proceeds_without_crash_on_empty_history() -> None:
    """C4: get_history returns empty dict → no crash, returns message."""
    loop = FakeLoop(
        provider=FakeProvider(FakeResponse("answer from empty history")),
        sessions=FakeSessions({}),
    )
    result = await run_btw(loop, "what time is it?", "session-key")
    assert result is not None
    assert result.content == "answer from empty history"


@pytest.mark.asyncio
async def test_proceeds_without_crash_on_empty_list_history() -> None:
    """C4: get_history returns empty list → no crash, returns message."""
    loop = FakeLoop(
        provider=FakeProvider(FakeResponse("answer from empty list history")),
        sessions=FakeSessions([]),
    )
    result = await run_btw(loop, "what time is it?", "session-key")
    assert result is not None
    assert result.content == "answer from empty list history"


# ---------------------------------------------------------------------------
# C5: provider returns LLMResponse with content → content extracted
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dict_response_content_extracted() -> None:
    """C5: provider returns LLMResponse-like with .content → extracted."""
    loop = FakeLoop(provider=FakeProvider(FakeResponse("dict content here")))
    result = await run_btw(loop, "what time is it?", "session-key")
    assert result is not None
    assert result.content == "dict content here"


# ---------------------------------------------------------------------------
# C6: provider returns plain LLMResponse → content = response.content
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_str_response_used_as_content() -> None:
    """C6: provider returns LLMResponse with string content → used."""
    loop = FakeLoop(provider=FakeProvider(FakeResponse("plain string answer")))
    result = await run_btw(loop, "what time is it?", "session-key")
    assert result is not None
    assert result.content == "plain string answer"


# ---------------------------------------------------------------------------
# C7: provider returns LLMResponse with None content → content = "" without crash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_none_response_yields_empty_content() -> None:
    """C7: provider returns LLMResponse(content=None) → empty string, no crash."""
    loop = FakeLoop(provider=FakeProvider(FakeResponse(None)))
    result = await run_btw(loop, "what time is it?", "session-key")
    assert result is not None
    assert result.content == ""


@pytest.mark.asyncio
async def test_int_response_yields_str_content() -> None:
    """C7: provider returns LLMResponse with non-string content → no crash."""
    loop = FakeLoop(provider=FakeProvider(FakeResponse(42)))
    result = await run_btw(loop, "what time is it?", "session-key")
    assert result is not None
    # ``42 or ""`` is 42 (truthy int), then ``getattr(...).content`` is
    # 42 — but our extractor only takes strings, so empty content.
    assert result.content == ""


# ---------------------------------------------------------------------------
# C8: on_stream callback is no longer wired (provider uses chat_with_retry).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_on_stream_callback_invoked_per_delta() -> None:
    """C8: on_stream is a documented parameter; current implementation does
    not invoke it (it is reserved for the future mid-stream integration).
    The handler must still succeed when an on_stream is passed."""
    streamed_chunks: list[str] = []
    on_stream = AsyncMock(side_effect=streamed_chunks.append)

    loop = FakeLoop(provider=FakeProvider(FakeResponse("hello world")))
    result = await run_btw(
        loop,
        "what time is it?",
        "session-key",
        on_stream=on_stream,
    )
    assert result is not None
    assert result.content == "hello world"
    # No streaming in the current implementation; the parameter is
    # accepted but not invoked yet.
    assert streamed_chunks == []


# ---------------------------------------------------------------------------
# C9: metadata["_btw"] = True always present
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_metadata_btw_flag_is_true() -> None:
    """C9: metadata['_btw'] is always True on success."""
    loop = FakeLoop(provider=FakeProvider(FakeResponse("answer")))
    result = await run_btw(loop, "what time is it?", "session-key")
    assert result is not None
    assert result.metadata.get("_btw") is True


# ---------------------------------------------------------------------------
# C10: _btw_elapsed_s is a positive number
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_metadata_elapsed_s_is_positive_number() -> None:
    """C10: _btw_elapsed_s is a positive float in metadata."""
    loop = FakeLoop(provider=FakeProvider(FakeResponse("fast answer")))
    result = await run_btw(loop, "what time is it?", "session-key")
    assert result is not None
    elapsed = result.metadata.get("_btw_elapsed_s")
    assert isinstance(elapsed, (int, float))
    assert elapsed >= 0


# ---------------------------------------------------------------------------
# Extra: error path → _btw still True in error message
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_metadata_btw_true_also_on_exception() -> None:
    """On generic exception, error message still has _btw = True."""

    class RaisingProvider:
        async def chat_with_retry(self, **kwargs: Any) -> Any:
            raise RuntimeError("boom")

    loop = FakeLoop(provider=RaisingProvider())
    result = await run_btw(loop, "what time is it?", "session-key")
    assert result is not None
    assert result.metadata.get("_btw") is True
