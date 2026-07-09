"""Per-session lock tests for Femtobot.run (B1).

B1 (REFACTOR_PLAN.md Lote B): ``Femtobot.run`` now serializes concurrent
calls on the same ``session_key`` via a per-instance
``WeakValueDictionary[str, asyncio.Lock]``.  A timed-out acquisition
raises ``asyncio.TimeoutError`` so SDK callers can decide whether to
retry, fail, or queue.

These tests stub out ``AgentLoop.process_direct`` so we can:
* verify that two concurrent calls on the same key are serialized,
* verify that two concurrent calls on *different* keys run in parallel,
* verify that a 0s timeout disables locking (escape hatch).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from femtobot.femtobot import Femtobot

pytestmark = [pytest.mark.durability, pytest.mark.asyncio]


class _StubLoop:
    """Minimal stand-in for ``AgentLoop`` that records call ordering."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, float]] = []
        self._extra_hooks: list[Any] = []
        # Sleep duration for the simulated LLM call.
        self.delay_s = 0.1

    async def process_direct(
        self,
        message: str,
        *,
        session_key: str,
        **_kwargs: Any,
    ) -> Any:
        # Record the start, then sleep to widen the overlap window.
        self.calls.append((session_key, time.monotonic()))
        await asyncio.sleep(self.delay_s)
        from femtobot.providers.base import LLMResponse

        return LLMResponse(content=f"echo: {message}", finish_reason="stop")


def _new_bot(timeout_s: float = 5.0) -> Femtobot:
    bot = Femtobot.__new__(Femtobot)  # type: ignore[call-arg]
    bot._loop = _StubLoop()  # type: ignore[attr-defined]
    import weakref

    bot._sdk_locks = weakref.WeakValueDictionary()  # type: ignore[attr-defined]
    bot._sdk_locks_lock = asyncio.Lock()  # type: ignore[attr-defined]
    bot._lock_timeout_s = float(timeout_s)  # type: ignore[attr-defined]
    return bot


async def test_same_session_key_serialized() -> None:
    """B1: two concurrent calls on the same key run sequentially (B1)."""
    bot = _new_bot(timeout_s=2.0)
    # Each call sleeps 0.1s; serialized → at least 0.2s.  In parallel
    # they'd take only 0.1s.  We give a generous margin.
    start = time.monotonic()
    await asyncio.gather(
        bot.run("a", session_key="k1"),
        bot.run("b", session_key="k1"),
    )
    elapsed = time.monotonic() - start
    assert elapsed >= 0.18, f"expected serialization, took {elapsed:.3f}s"


async def test_different_session_keys_run_in_parallel() -> None:
    """B1: concurrent calls on different keys are NOT serialized (B1)."""
    bot = _new_bot(timeout_s=2.0)
    start = time.monotonic()
    await asyncio.gather(
        bot.run("a", session_key="k1"),
        bot.run("b", session_key="k2"),
    )
    elapsed = time.monotonic() - start
    assert elapsed < 0.18, f"different keys should run in parallel, took {elapsed:.3f}s"


async def test_session_lock_can_be_acquired() -> None:
    """B1: a single call on a fresh key acquires and releases the lock (B1)."""
    bot = _new_bot(timeout_s=2.0)
    result = await bot.run("hello", session_key="only")
    assert "echo" in result.content


async def test_zero_timeout_disables_locking() -> None:
    """B1: lock_timeout_s=0 runs both calls in parallel (escape hatch)."""
    bot = _new_bot(timeout_s=0.0)
    start = time.monotonic()
    await asyncio.gather(
        bot.run("a", session_key="shared"),
        bot.run("b", session_key="shared"),
    )
    elapsed = time.monotonic() - start
    # Both 0.1s sleeps in parallel → ~0.1s.
    assert elapsed < 0.18, f"lock should be disabled, took {elapsed:.3f}s"


async def test_lock_timeout_raises() -> None:
    """B1: a 0.01s timeout against a held lock raises asyncio.TimeoutError (B1)."""
    bot = _new_bot(timeout_s=0.01)

    # Hold the lock manually so the next call cannot acquire it.
    lock = await bot._acquire_session_lock("blocked")  # type: ignore[attr-defined]
    await lock.acquire()
    try:
        with pytest.raises(asyncio.TimeoutError):
            await bot.run("a", session_key="blocked")
    finally:
        lock.release()


async def test_extra_hooks_restored_on_lock_timeout() -> None:
    """B1: ``_extra_hooks`` is restored even when the lock times out.

    Regression guard: an earlier revision put the restore after the
    lock try/finally, so a timeout (which raises before
    ``process_direct``) leaked the SDKCaptureHook into the next run.
    """
    bot = _new_bot(timeout_s=0.01)
    sentinel_hooks: list[Any] = []
    bot._loop._extra_hooks = sentinel_hooks  # type: ignore[attr-defined]

    # Hold the lock so the next call must time out.
    lock = await bot._acquire_session_lock("restore-check")  # type: ignore[attr-defined]
    await lock.acquire()
    try:
        with pytest.raises(asyncio.TimeoutError):
            await bot.run("a", session_key="restore-check")
    finally:
        lock.release()

    # The pre-existing _extra_hooks list must be back, NOT a list
    # with the capture hook appended.
    assert bot._loop._extra_hooks is sentinel_hooks, (  # type: ignore[attr-defined]
        f"expected _extra_hooks to be restored, got {bot._loop._extra_hooks!r}"
    )


async def test_extra_hooks_restored_after_successful_run() -> None:
    """B1: ``_extra_hooks`` is restored on the happy path (B1)."""
    bot = _new_bot(timeout_s=2.0)
    sentinel_hooks: list[Any] = []
    bot._loop._extra_hooks = sentinel_hooks  # type: ignore[attr-defined]
    await bot.run("hi", session_key="restore-success")
    assert bot._loop._extra_hooks is sentinel_hooks  # type: ignore[attr-defined]
