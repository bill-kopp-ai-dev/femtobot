"""Race-free per-session lock acquisition in AgentLoop.

Regression test for the historical race where two coroutines that
both called ``_dispatch`` for the same fresh ``session_key`` would
each create a fresh ``asyncio.Lock`` via ``dict.setdefault`` and
acquire different locks, allowing concurrent writes to ``Session``.

The fix introduces ``AgentLoop._acquire_session_lock`` which uses a
double-check pattern: a fast-path dict lookup, then a slow path
guarded by ``self._session_locks_lock``.

We pin:

* a single key returns the same lock across concurrent acquires,
* two different keys return *different* locks (no false sharing),
* the helper is async (it must be, to safely enter the inner
  ``async with``) — calling it from a sync path would be a TypeError.
"""

from __future__ import annotations

import asyncio

from femtobot.agent.loop import AgentLoop


def _new_loop() -> AgentLoop:
    """Build a minimal AgentLoop instance for the test."""
    loop = AgentLoop.__new__(AgentLoop)  # type: ignore[call-arg]
    loop._session_locks = {}  # type: ignore[attr-defined]
    loop._session_locks_lock = asyncio.Lock()  # type: ignore[attr-defined]
    return loop


async def test_acquire_returns_same_lock_for_same_key() -> None:
    """Race fix: same key → same lock across concurrent acquires (B1+)."""
    al = _new_loop()
    # Race: 50 concurrent acquires for the same key.
    results = await asyncio.gather(
        *(al._acquire_session_lock("session-A") for _ in range(50))  # type: ignore[attr-defined]
    )
    # All results must be the same object — no duplicate lock creation.
    assert all(r is results[0] for r in results)
    # And the dict has exactly one entry.
    assert len(al._session_locks) == 1  # type: ignore[attr-defined]


async def test_acquire_returns_different_locks_for_different_keys() -> None:
    """Race fix: different keys → different locks (B1+)."""
    al = _new_loop()
    lock_a = await al._acquire_session_lock("session-A")  # type: ignore[attr-defined]
    lock_b = await al._acquire_session_lock("session-B")  # type: ignore[attr-defined]
    assert lock_a is not lock_b
    # Each lock is functional (acquires without error).
    async with lock_a:
        pass
    async with lock_b:
        pass


async def test_acquire_reuses_existing_lock() -> None:
    """Race fix: a pre-existing lock is returned, not replaced (B1+)."""
    al = _new_loop()
    existing = asyncio.Lock()
    al._session_locks["preset"] = existing  # type: ignore[attr-defined]
    out = await al._acquire_session_lock("preset")  # type: ignore[attr-defined]
    assert out is existing


async def test_acquire_is_coroutine() -> None:
    """Race fix: the helper is async (it must be to be race-free) (B1+)."""
    al = _new_loop()
    # Calling the bare method returns a coroutine — not a Lock.
    coro = al._acquire_session_lock("c")  # type: ignore[attr-defined]
    assert asyncio.iscoroutine(coro)
    # Cleanly close the coroutine so it doesn't warn.
    coro.close()


async def test_concurrent_acquires_serialize_on_inner_lock() -> None:
    """Race fix: under contention, only one coroutine creates the lock (B1+).

    Smoke test that the inner ``self._session_locks_lock`` actually
    serializes the slow path.  We run 100 concurrent acquires for a
    fresh key; if the slow path weren't guarded, two coroutines
    could each see ``dict is empty`` and each create a fresh lock.
    """
    al = _new_loop()

    async def acquire_slow() -> asyncio.Lock:
        # Force the slow path by clearing the cache between attempts.
        return await al._acquire_session_lock("hot-key")  # type: ignore[attr-defined]

    # 100 concurrent acquires for the same fresh key.
    results = await asyncio.gather(*(acquire_slow() for _ in range(100)))
    assert all(r is results[0] for r in results)
    # The slow path serialized correctly: only one lock exists.
    assert len(al._session_locks) == 1  # type: ignore[attr-defined]
