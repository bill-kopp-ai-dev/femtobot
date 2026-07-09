"""Tests for femtobot.cli.btw — /btw side-question handler."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from femtobot.cli.btw import run_btw

# ---------------------------------------------------------------------------
# Fake helpers
# ---------------------------------------------------------------------------


class FakeProvider:
    """Minimal provider that returns a configurable response."""

    def __init__(self, response: Any) -> None:
        self._response = response

    async def generate(
        self, *, messages: list, tools: Any, on_stream: Any = None
    ) -> Any:
        if on_stream:
            for chunk in str(self._response).split():
                await on_stream(chunk)
        return self._response


class FakeProviderNoGenerate:
    """Provider that lacks the generate method."""

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
    loop = FakeLoop(provider=FakeProvider("hello world"))
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
        provider=FakeProvider("answer from empty history"),
        sessions=FakeSessions({}),
    )
    result = await run_btw(loop, "what time is it?", "session-key")
    assert result is not None
    assert result.content == "answer from empty history"


@pytest.mark.asyncio
async def test_proceeds_without_crash_on_empty_list_history() -> None:
    """C4: get_history returns empty list → no crash, returns message."""
    loop = FakeLoop(
        provider=FakeProvider("answer from empty list history"),
        sessions=FakeSessions([]),
    )
    result = await run_btw(loop, "what time is it?", "session-key")
    assert result is not None
    assert result.content == "answer from empty list history"


# ---------------------------------------------------------------------------
# C5: provider returns dict with content → content extracted
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dict_response_content_extracted() -> None:
    """C5: provider returns dict with content key → content extracted."""
    loop = FakeLoop(provider=FakeProvider({"content": "dict content here"}))
    result = await run_btw(loop, "what time is it?", "session-key")
    assert result is not None
    assert result.content == "dict content here"


# ---------------------------------------------------------------------------
# C6: provider returns raw str → content = result
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_str_response_used_as_content() -> None:
    """C6: provider returns a plain string → used as content."""
    loop = FakeLoop(provider=FakeProvider("plain string answer"))
    result = await run_btw(loop, "what time is it?", "session-key")
    assert result is not None
    assert result.content == "plain string answer"


# ---------------------------------------------------------------------------
# C7: provider returns None/other type → content = "" without crash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_none_response_yields_empty_content() -> None:
    """C7: provider returns None → content is empty string, no crash."""
    loop = FakeLoop(provider=FakeProvider(None))
    result = await run_btw(loop, "what time is it?", "session-key")
    assert result is not None
    assert result.content == ""


@pytest.mark.asyncio
async def test_int_response_yields_str_content() -> None:
    """C7: provider returns unsupported type (int) → str() used, no crash."""
    loop = FakeLoop(provider=FakeProvider(42))
    result = await run_btw(loop, "what time is it?", "session-key")
    assert result is not None
    assert result.content == "42"


# ---------------------------------------------------------------------------
# C8: on_stream callback is invoked
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_on_stream_callback_invoked_per_delta() -> None:
    """C8: on_stream callback is called once per word delta."""
    streamed_chunks: list[str] = []
    on_stream = AsyncMock(side_effect=streamed_chunks.append)

    loop = FakeLoop(provider=FakeProvider("hello world"))
    result = await run_btw(
        loop,
        "what time is it?",
        "session-key",
        on_stream=on_stream,
    )
    assert result is not None
    # Each word is a separate delta (split on whitespace).
    assert len(streamed_chunks) == 2
    assert streamed_chunks[0] == "hello"
    assert streamed_chunks[1] == "world"


# ---------------------------------------------------------------------------
# C9: metadata["_btw"] = True always present
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_metadata_btw_flag_is_true() -> None:
    """C9: metadata['_btw'] is always True on success."""
    loop = FakeLoop(provider=FakeProvider("answer"))
    result = await run_btw(loop, "what time is it?", "session-key")
    assert result is not None
    assert result.metadata.get("_btw") is True


# ---------------------------------------------------------------------------
# C10: _btw_elapsed_s is a positive number
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_metadata_elapsed_s_is_positive_number() -> None:
    """C10: _btw_elapsed_s is a positive float in metadata."""
    loop = FakeLoop(provider=FakeProvider("fast answer"))
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
        async def generate(self, **kwargs: Any) -> Any:
            raise RuntimeError("boom")

    loop = FakeLoop(provider=RaisingProvider())
    result = await run_btw(loop, "what time is it?", "session-key")
    assert result is not None
    assert result.metadata.get("_btw") is True
