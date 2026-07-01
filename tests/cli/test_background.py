"""Tests for the background module (Camada 2, T2.5)."""

from __future__ import annotations

import asyncio

import pytest

from femtobot.cli.background import BackgroundPool, BackgroundTask, TaskState


@pytest.mark.asyncio
async def test_submit_and_wait() -> None:
    pool = BackgroundPool()

    async def sample():
        await asyncio.sleep(0.01)
        return 42

    task_id = pool.submit(sample(), label="test")
    assert task_id.startswith("bg-")
    # Wait for completion
    await asyncio.sleep(0.05)
    entry = pool._tasks[task_id]
    assert entry.state == TaskState.DONE
    assert entry.result == 42


@pytest.mark.asyncio
async def test_cancel_all() -> None:
    pool = BackgroundPool()

    async def slow():
        await asyncio.sleep(10.0)
        return "done"

    pool.submit(slow(), label="slow")
    # Give the event loop one tick so the task enters RUNNING state.
    await asyncio.sleep(0)
    assert pool.running_count() == 1
    cancelled = pool.cancel_all()
    assert cancelled == 1


@pytest.mark.asyncio
async def test_status_ordering() -> None:
    pool = BackgroundPool()

    async def quick():
        return 1

    id1 = pool.submit(quick(), label="a")
    id2 = pool.submit(quick(), label="b")
    await asyncio.sleep(0.05)
    status = pool.status()
    assert status[0].task_id == id1
    assert status[1].task_id == id2


@pytest.mark.asyncio
async def test_prune_removes_old_done() -> None:
    pool = BackgroundPool()
    # Manually insert a done task with old timestamp (bypass submit).
    import time
    entry = BackgroundTask(
        task_id="old",
        label="old",
        coroutine=asyncio.sleep(0),  # valid awaitable
    )
    entry.state = TaskState.DONE
    entry.finished_at = time.monotonic() - 400
    pool._tasks["old"] = entry
    removed = pool.prune_done(max_age_s=300)
    assert removed == 1
    assert "old" not in pool._tasks
