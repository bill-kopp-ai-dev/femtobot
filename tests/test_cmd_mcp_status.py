"""Tests for ``cmd_mcp`` status subcommand enhancements.

Added in PR 1.1 of the ``longlogs.txt`` remediation plan.

Covers:
- ``/mcp status`` surfaces ``referenced but not configured`` when the
  session metadata carries an ``mcp_missing`` list.
- ``/mcp path <server>`` prints transport / command / url / cwd.
- ``/mcp path <server>`` with an unknown server prints a clear error.
- The unknown-subcommand help string mentions ``path``.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from femtobot.command import builtin as cmd_module
from femtobot.command.router import CommandContext


class _FakeToolRegistry:
    tool_names: list[str] = []


class _FakeSessions:
    def __init__(self, metadata: dict | None = None) -> None:
        self._metadata = metadata or {}

    def get_or_create(self, key: str):  # noqa: ANN001
        return SimpleNamespace(key=key, metadata=self._metadata)


class _FakeLoop:
    def __init__(self, metadata: dict | None = None) -> None:
        self._mcp_servers: dict = {}
        self._mcp_stacks: dict = {}
        self.tools = _FakeToolRegistry()
        self.sessions = _FakeSessions(metadata)


def _ctx(loop: _FakeLoop, args: str) -> CommandContext:
    """Build a CommandContext as if it had been routed through ``router.dispatch``.

    ``cmd_mcp`` reads ``ctx.args`` (already stripped of the ``/mcp ``
    prefix by the router). The test fixtures must mirror that.
    """
    msg = SimpleNamespace(
        channel="cli",
        chat_id="direct",
        metadata={},
        content="/mcp",
    )
    return CommandContext(
        msg=msg,
        session=None,
        key="cli:direct",
        raw="/mcp",
        args=args,
        loop=loop,
    )


def _run(coro):  # noqa: ANN001
    """Run the coroutine using a fresh asyncio loop per call.

    ``asyncio.get_event_loop().run_until_complete`` would reuse a
    closed loop across tests; ``asyncio.run`` is the safe default.
    """
    return asyncio.run(coro)


def test_status_lists_referenced_but_not_configured():
    loop = _FakeLoop(metadata={"mcp_missing": ["percival-osm", "agy"]})
    out = _run(cmd_module.cmd_mcp(_ctx(loop, "status")))
    assert out is not None
    assert "percival-osm" in out.content
    assert "agy" in out.content
    assert "referenced but not configured" in out.content


def test_status_no_referenced_when_metadata_empty():
    loop = _FakeLoop(metadata={})
    out = _run(cmd_module.cmd_mcp(_ctx(loop, "status")))
    assert out is not None
    assert "referenced but not configured" not in out.content


def test_path_prints_transport_for_configured_server():
    cfg = SimpleNamespace(command="percival-osm-mcp", url="-", type="stdio", cwd="/tmp")
    loop = _FakeLoop()
    loop._mcp_servers = {"percival-osm": cfg}
    out = _run(cmd_module.cmd_mcp(_ctx(loop, "path percival-osm")))
    assert out is not None
    assert "transport: stdio" in out.content
    assert "command:   percival-osm-mcp" in out.content


def test_path_unknown_server_returns_actionable_error():
    loop = _FakeLoop()
    out = _run(cmd_module.cmd_mcp(_ctx(loop, "path no-such-server")))
    assert out is not None
    assert "is not configured" in out.content


def test_path_without_server_returns_usage():
    loop = _FakeLoop()
    out = _run(cmd_module.cmd_mcp(_ctx(loop, "path")))
    assert out is not None
    assert "Usage: /mcp path <server>" in out.content


def test_unknown_subcommand_help_mentions_path():
    loop = _FakeLoop()
    out = _run(cmd_module.cmd_mcp(_ctx(loop, "wat")))
    assert out is not None
    assert "path <server>" in out.content
