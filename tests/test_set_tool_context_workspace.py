"""Test that ``AgentLoop._set_tool_context`` injects ``workspace`` into metadata.

Refs: FEMTOBOT_MCP_IMPROVEMENT_PLAN.md Fase 3 (workspace auto-fill).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from femtobot.agent.tools.context import (
    ContextAware,
    RequestContext,
)


def _make_loop(workspace: Path | None) -> SimpleNamespace:
    """Build a stand-in AgentLoop exposing just what ``_set_tool_context`` reads."""
    loop = SimpleNamespace()
    loop.workspace = workspace
    loop._unified_session = False
    # A no-op ``tools`` registry — we don't test tool registration here.
    loop.tools = MagicMock()
    loop.tools.tool_names = []
    return loop


@pytest.mark.asyncio
async def test_set_tool_context_injects_workspace_path(tmp_path: Path) -> None:
    """``_set_tool_context`` adds ``metadata['workspace']`` from ``self.workspace``."""
    from femtobot.agent.loop import AgentLoop

    ws = tmp_path / "work"
    ws.mkdir()
    loop = _make_loop(workspace=ws)

    # Capture the RequestContext via the ContextAware.bind_request_context mechanism.
    captured: list[RequestContext] = []

    class _Capturing(ContextAware):
        def set_context(self, ctx: RequestContext) -> None:
            captured.append(ctx)

    fake_tool_instance = _Capturing()
    loop.tools.tool_names = ["capture"]
    loop.tools.get = MagicMock(return_value=fake_tool_instance)

    AgentLoop._set_tool_context(  # type: ignore[arg-type]
        loop,
        channel="cli",
        chat_id="c1",
        message_id=None,
        metadata={"foo": "bar"},
        session_key="cli:c1",
    )

    assert captured, "ContextAware.set_context was not called"
    meta = captured[0].metadata
    assert meta["workspace"] == str(ws)
    assert meta["foo"] == "bar"  # original metadata preserved


@pytest.mark.asyncio
async def test_set_tool_context_does_not_overwrite_explicit_workspace(tmp_path: Path) -> None:
    """An explicit ``workspace`` in metadata is preserved (caller wins)."""
    from femtobot.agent.loop import AgentLoop

    ws = tmp_path / "work"
    ws.mkdir()
    loop = _make_loop(workspace=ws)

    captured: list[RequestContext] = []

    class _Capturing(ContextAware):
        def set_context(self, ctx: RequestContext) -> None:
            captured.append(ctx)

    loop.tools.tool_names = ["capture"]
    loop.tools.get = MagicMock(return_value=_Capturing())

    AgentLoop._set_tool_context(  # type: ignore[arg-type]
        loop,
        channel="cli",
        chat_id="c1",
        metadata={"workspace": "/explicit/override"},
    )

    assert captured[0].metadata["workspace"] == "/explicit/override"


@pytest.mark.asyncio
async def test_set_tool_context_works_without_workspace_attr(tmp_path: Path) -> None:
    """Defensive: missing ``workspace`` attr does not crash."""
    from femtobot.agent.loop import AgentLoop

    loop = SimpleNamespace()
    # Intentionally no ``workspace`` attr
    loop._unified_session = False
    loop.tools = MagicMock()
    loop.tools.tool_names = []

    # Should not raise.
    AgentLoop._set_tool_context(  # type: ignore[arg-type]
        loop,
        channel="cli",
        chat_id="c1",
        metadata=None,
    )
