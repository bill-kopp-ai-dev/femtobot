"""Background task pool for the CLI — supports Ctrl+B backgrounding.

Inspired by Claude Code's Ctrl+B background bash:
``FEMTOBOT_CLI_REFACTOR_PLAN.md`` Camada 2, T2.5.

Usage
~~~~~
::

    from femtobot.cli.background import BackgroundPool, submit_background_task

    pool = BackgroundPool()

    async def my_task():
        await asyncio.sleep(1)
        return "done"

    task_id = pool.submit(my_task(), label="test")
    status = pool.status()
    # In the REPL, /tasks shows all running background tasks.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class TaskState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BackgroundTask:
    """A single background task in the pool."""

    task_id: str
    label: str
    coroutine: Awaitable
    _handle: asyncio.Task | None = field(default=None, repr=False)
    state: TaskState = TaskState.PENDING
    submitted_at: float = field(default_factory=time.monotonic)
    started_at: float | None = None
    finished_at: float | None = None
    result: Any = None
    error: str | None = None

    @property
    def elapsed_s(self) -> float | None:
        if self.started_at is None:
            return None
        end = self.finished_at or time.monotonic()
        return end - self.started_at

    @property
    def summary(self) -> str:
        if self.state == TaskState.RUNNING:
            elapsed = f"{self.elapsed_s:.1f}s" if self.elapsed_s else "?"
            return f"[yellow]{self.label}[/yellow] · running {elapsed}"
        elif self.state == TaskState.DONE:
            elapsed = f"{self.elapsed_s:.1f}s" if self.elapsed_s else "?"
            return f"[green]{self.label}[/green] · done in {elapsed}"
        elif self.state == TaskState.FAILED:
            return f"[red]{self.label}[/red] · failed: {self.error or 'unknown'}"
        elif self.state == TaskState.CANCELLED:
            return f"[dim]{self.label}[/dim] · cancelled"
        return f"[dim]{self.label}[/dim] · pending"


# ---------------------------------------------------------------------------
# Pool
# ---------------------------------------------------------------------------

import uuid


class BackgroundPool:
    """Manages a set of background asyncio tasks."""

    def __init__(self):
        self._tasks: dict[str, BackgroundTask] = {}
        self._counter: int = 0

    def submit(
        self,
        coro: Awaitable,
        label: str = "background",
    ) -> str:
        """Submit a coroutine to run in the background. Returns the task_id."""
        self._counter += 1
        task_id = f"bg-{self._counter:03d}"
        entry = BackgroundTask(task_id=task_id, label=label, coroutine=coro)
        self._tasks[task_id] = entry
        handle = asyncio.create_task(self._run(entry))
        entry._handle = handle
        return task_id

    async def _run(self, entry: BackgroundTask) -> None:
        entry.state = TaskState.RUNNING
        entry.started_at = time.monotonic()
        try:
            result = await entry.coroutine
            entry.result = result
            entry.state = TaskState.DONE
        except asyncio.CancelledError:
            entry.state = TaskState.CANCELLED
        except Exception as exc:
            entry.state = TaskState.FAILED
            entry.error = str(exc)
        finally:
            entry.finished_at = time.monotonic()

    def cancel(self, task_id: str) -> bool:
        """Cancel a background task by id. Returns True if cancelled."""
        entry = self._tasks.get(task_id)
        if entry is None or entry._handle is None:
            return False
        entry._handle.cancel()
        return True

    def cancel_all(self) -> int:
        """Cancel all running tasks. Returns the count cancelled."""
        count = 0
        for entry in self._tasks.values():
            if entry.state == TaskState.RUNNING and entry._handle:
                entry._handle.cancel()
                count += 1
        return count

    def status(self) -> list[BackgroundTask]:
        """All tasks ordered by submission time."""
        return sorted(self._tasks.values(), key=lambda t: t.submitted_at)

    def running_count(self) -> int:
        return sum(1 for t in self._tasks.values() if t.state == TaskState.RUNNING)

    def prune_done(self, max_age_s: float = 300.0) -> int:
        """Remove done/cancelled tasks older than max_age_s. Returns count removed."""
        now = time.monotonic()
        to_remove = [
            tid for tid, t in self._tasks.items()
            if t.state in (TaskState.DONE, TaskState.FAILED, TaskState.CANCELLED)
            and (t.finished_at or 0) < now - max_age_s
        ]
        for tid in to_remove:
            del self._tasks[tid]
        return len(to_remove)
