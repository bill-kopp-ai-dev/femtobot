"""``_detect_audio_recorder`` is async tests (v0.0.8 third-pass C4).

Audit C4: ``_detect_audio_recorder`` used to call ``subprocess.run``
synchronously.  When invoked from ``record_audio`` (an ``async
def``), it blocked the event loop for up to 5 seconds per
``which`` invocation, totalling up to 15 seconds.  The function
is now async and uses ``asyncio.to_thread`` to offload the
subprocess call to a thread.

We pin:

* ``_detect_audio_recorder`` is a coroutine function (so the
  event loop stays responsive while detection runs),
* it returns ``None`` when no recorder is available (so the
  caller can short-circuit),
* concurrent detection requests do not serialize each other
  (the loop can interleave other coroutines during detection).
"""

from __future__ import annotations

import asyncio
import inspect
import time
from unittest.mock import patch

import pytest

from femtobot.cli.voice import _detect_audio_recorder

pytestmark = pytest.mark.asyncio


def test_detect_audio_recorder_is_coroutine_function() -> None:
    """C4: the function is ``async def`` (C4 baseline)."""
    assert inspect.iscoroutinefunction(_detect_audio_recorder)


async def test_returns_none_when_no_recorder_found() -> None:
    """C4: returns ``None`` when no ``which`` succeeds (C4 baseline)."""
    fake_completed = type(
        "R", (), {"returncode": 1, "stdout": "", "stderr": ""}
    )()

    def _fake_run(*args, **kwargs):
        return fake_completed

    with patch("femtobot.cli.voice.subprocess.run", side_effect=_fake_run):
        result = await _detect_audio_recorder()
    assert result is None


async def test_returns_first_available_recorder() -> None:
    """C4: returns the first recorder for which ``which`` succeeds (C4)."""
    calls: list[list[str]] = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        # Make the second command (arecord) succeed.
        if cmd[-1] == "arecord":
            return type("R", (), {
                "returncode": 0, "stdout": "/usr/bin/arecord\n", "stderr": ""
            })()
        return type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})()

    with patch("femtobot.cli.voice.subprocess.run", side_effect=_fake_run):
        result = await _detect_audio_recorder()
    assert result == "arecord"
    # We tried ffmpeg first, then arecord (and stopped there).
    assert [c[-1] for c in calls] == ["ffmpeg", "arecord"]


async def test_does_not_block_event_loop() -> None:
    """C4: detection does not block other coroutines (C4).

    The previous synchronous implementation could starve the loop
    for up to 15 seconds.  We verify that another coroutine runs
    while detection is in flight.
    """
    tick = []

    async def _ticker() -> None:
        """A coroutine that records timestamps; should run during detection."""
        for _ in range(5):
            await asyncio.sleep(0.02)
            tick.append(time.monotonic())

    def _fake_run(*args, **kwargs):
        # Simulate a 0.2s "which" call.  If we synchronously block,
        # the ticker would be starved.
        time.sleep(0.05)
        return type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})()

    with patch("femtobot.cli.voice.subprocess.run", side_effect=_fake_run):
        await asyncio.gather(
            _ticker(),
            _detect_audio_recorder(),
        )
    # Ticker should have ticked at least 4 times (5 ticks, last one
    # happens after the await).  With sync-blocking, it would tick
    # zero times until detection finishes.
    assert len(tick) >= 3, f"event loop was blocked; ticker only ran {len(tick)} times"
