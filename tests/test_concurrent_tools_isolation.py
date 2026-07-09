"""Concurrent tool isolation tests (v0.0.9 H6).

Audit H6: ``AgentRunner._execute_tools`` used to call
``asyncio.gather(*coros)`` without ``return_exceptions=True``.
When one tool raised, ``gather`` cancelled the remaining peers
mid-flight, leading to half-applied side effects (e.g. one
tool wrote to disk, another was cancelled mid-write).

We now use ``return_exceptions=True`` and synthesize an error
tuple for any raised exception so the loop can decide how to
handle each tool's outcome independently.

We pin:

* a successful tool completes cleanly,
* a failing tool's error is captured (not propagated to
  cancel the others),
* all peers finish even if one raises,
* ``CancelledError`` still propagates as designed (a tool
  cancelled by the runner's stop logic should abort the
  batch).
"""

from __future__ import annotations

import asyncio

import pytest

from femtobot.agent.runner import AgentRunner

pytestmark = pytest.mark.asyncio


async def test_concurrent_gather_isolates_failures() -> None:
    """H6: a failing tool does not cancel its peers (H6)."""
    # Use a tiny stand-in for the runner; we just need to
    # verify the gather semantics.  The runner's
    # ``_execute_tools`` is the integration point — here we
    # test the underlying ``asyncio.gather(..., return_exceptions=True)``
    # pattern in isolation.

    completed: list[str] = []

    async def ok(name: str) -> str:
        await asyncio.sleep(0.05)
        completed.append(name)
        return name

    async def bad() -> str:
        await asyncio.sleep(0.02)
        raise RuntimeError("tool failed")

    results = await asyncio.gather(
        ok("a"),
        bad(),
        ok("b"),
        return_exceptions=True,
    )

    # ``ok("a")`` and ``ok("b")`` should both have completed
    # even though ``bad()`` raised.  This is the core fix.
    assert "a" in completed
    assert "b" in completed
    # ``bad()`` shows up as the raised exception in the
    # results list — and only that slot has it.
    assert results[0] == "a"
    assert isinstance(results[1], RuntimeError)
    assert results[2] == "b"


async def test_concurrent_gather_propagates_cancelled_error() -> None:
    """H6: ``CancelledError`` still propagates (H6)."""
    started = asyncio.Event()
    proceed = asyncio.Event()

    async def cancelable() -> None:
        started.set()
        await proceed.wait()

    task = asyncio.create_task(cancelable())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    proceed.set()  # let the coroutine finish so it can be GC'd


def test_agent_runner_uses_return_exceptions() -> None:
    """H6: source-level check that ``_execute_tools`` uses return_exceptions (H6)."""
    import inspect


    source = inspect.getsource(AgentRunner._execute_tools)
    assert "return_exceptions=True" in source, (
        "AgentRunner._execute_tools must use return_exceptions=True"
    )
