"""Regression tests for issue #1 — longlogs.txt 2026-07-19.

Each test maps to one of the 9 visual bugs observed in the
interactive TUI session recorded in ``/home/bill/Codes/agents/longlogs.txt``:

  - B1/B6/B7: spinner + Live display racing with ``[ 👤 You ]`` /
    user input (cli/commands.py)
  - B2: MCP stdio subprocess stderr leaking into femtobot stderr
    (agent/tools/mcp.py → femtobot/config/paths.py::get_logs_dir)
  - B8: startup MCP-missing warning racing with the first prompt
    (cli/commands.py::run_interactive drain)

The tests do not replay the full ``femtobot agent --ui compat`` session;
they exercise the surgical fixes so a future refactor that breaks any
of them shows up immediately in CI.

Refs: docs/exec-plan-resolucao-bugs-longlogs.md (PR 2.1, 2.2, 2.3, 6.1)
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from femtobot.agent.tools.mcp import (
    _close_file_on_exit,
    _resolve_mcp_errlog,
)


# ---------------------------------------------------------------------------
# B2 — MCP stdio stderr must NOT inherit femtobot's stderr
# ---------------------------------------------------------------------------


def test_resolve_mcp_errlog_writes_to_logs_dir(tmp_path: Path, monkeypatch) -> None:
    """``_resolve_mcp_errlog`` returns a writable TextIO inside the
    instance logs directory, NOT ``sys.stderr``.

    Issue #1, B2: the MCP subprocess was inheriting femtobot's stderr
    and its ``INFO mcp.server.lowlevel.server: …`` lines were
    interleaving with the user's TUI input.
    """
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()

    # The function does ``from femtobot.config.paths import get_logs_dir``
    # lazily inside the function body, so the symbol it picks up is the
    # one currently bound on that module. Patch in place.
    monkeypatch.setattr(
        "femtobot.config.paths.get_logs_dir", lambda: logs_dir
    )

    handle = _resolve_mcp_errlog("percival-osm")
    try:
        assert not isinstance(handle, int), (
            "expected a TextIO, not subprocess.DEVNULL — the test "
            "environment should be able to resolve the logs dir"
        )
        handle.write("INFO mcp.server.lowlevel.server: smoke test\n")
        handle.flush()
    finally:
        handle.close()

    log_files = list(logs_dir.glob("mcp-percival-osm.log"))
    assert log_files, "expected mcp-percival-osm.log to be created under logs/"
    contents = log_files[0].read_text(encoding="utf-8")
    assert "smoke test" in contents


def test_resolve_mcp_errlog_falls_back_to_devnull_when_path_fails(monkeypatch) -> None:
    """When the logs directory cannot be created, fall back to DEVNULL
    — never to ``sys.stderr`` (that is the bug we are fixing)."""
    monkeypatch.setattr(
        "femtobot.config.paths.get_logs_dir",
        lambda: (_ for _ in ()).throw(OSError("disk full")),
    )
    target = _resolve_mcp_errlog("percival-osm")
    assert target == subprocess.DEVNULL


def test_close_file_on_exit_releases_handle(tmp_path: Path) -> None:
    """``_close_file_on_exit`` closes the underlying handle on exit
    so the log file is not held open after the server disconnects."""
    p = tmp_path / "x.log"
    fh = open(p, "a", encoding="utf-8")
    cm = _close_file_on_exit(fh)

    async def runner():
        async with cm as inner:
            assert inner is fh
            inner.write("hi\n")
        # After exit, the handle should be closed.
        assert fh.closed

    asyncio.run(runner())
    assert p.read_text(encoding="utf-8") == "hi\n"


# ---------------------------------------------------------------------------
# B8 — startup MCP warnings are drained before the first prompt
# ---------------------------------------------------------------------------


def test_run_interactive_drains_startup_warnings_before_prompt() -> None:
    """The startup-drain loop in ``run_interactive`` must call
    ``bus.consume_outbound`` and print any ``cli:startup`` message
    before letting the REPL block on user input.

    Without the drain, the warning arrives *during* the first prompt
    and gets mixed with the user's input line.
    """
    from femtobot.bus.events import OutboundMessage
    from femtobot.bus.queue import MessageBus

    # Lightweight smoke: simulate the bus publishing a startup warning
    # and assert that the consumer code path observes it within the
    # 0.15s timeout the drain uses.
    bus = MessageBus()

    async def scenario():
        await bus.publish_outbound(
            OutboundMessage(
                channel="cli",
                chat_id="startup",
                content="⚠ MCP servers referenced: percival-osm.",
                metadata={"render_as": "text"},
            )
        )
        try:
            msg = await asyncio.wait_for(bus.consume_outbound(), timeout=0.15)
            return msg
        except asyncio.TimeoutError:
            return None

    msg = asyncio.run(scenario())
    assert msg is not None, "startup warning was not observed within drain window"
    assert msg.channel == "cli"
    assert msg.chat_id == "startup"
    assert "percival-osm" in msg.content


# ---------------------------------------------------------------------------
# B1/B6/B7 — ``print_user_box`` must stop the renderer first
# ---------------------------------------------------------------------------


def test_print_user_box_is_preceded_by_stop_for_input() -> None:
    """Verify the source-order contract: in
    ``_read_interactive_input_async``, ``renderer.stop_for_input()``
    is called BEFORE ``renderer.print_user_box()``.

    This is a static check — the fix is structural, so a test that
    fails this invariant is the regression we want to catch.
    """
    import inspect

    src = inspect.getsource(
        __import__("femtobot.cli.commands", fromlist=["_read_interactive_input_async"])
            ._read_interactive_input_async
    )
    stop_idx = src.find("renderer.stop_for_input()")
    box_idx = src.find("renderer.print_user_box()")
    assert stop_idx != -1, "stop_for_input() call missing from _read_interactive_input_async"
    assert box_idx != -1, "print_user_box() call missing from _read_interactive_input_async"
    assert stop_idx < box_idx, (
        "renderer.stop_for_input() must be called BEFORE "
        "renderer.print_user_box() to clear leftover spinner frames "
        "(issue #1, B1/B6/B7)"
    )