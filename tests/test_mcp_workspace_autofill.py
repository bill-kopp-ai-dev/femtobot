"""Tests for the workspace_path auto-fill behavior (Phase 3).

Refs: FEMTOBOT_MCP_IMPROVEMENT_PLAN.md Fase 3.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from femtobot.agent.tools.context import (
    RequestContext,
    bind_request_context,
    reset_request_context,
)
from femtobot.agent.tools.mcp import (
    _MCP_WORKSPACE_AWARE_TOOLS,
    _resolve_active_workspace,
    MCPToolWrapper,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_def(name: str, description: str = "stub", input_schema: dict | None = None) -> MagicMock:
    """Build a minimal stub matching the ``mcp.types.Tool`` interface."""
    tool_def = MagicMock()
    tool_def.name = name
    tool_def.description = description
    tool_def.inputSchema = input_schema or {"type": "object", "properties": {}}
    return tool_def


@contextmanager
def _request_workspace(workspace: str | None):
    """Bind a RequestContext whose metadata contains ``workspace=workspace``."""
    ctx = RequestContext(channel="cli", chat_id="test", metadata={"workspace": workspace})
    token = bind_request_context(ctx)
    try:
        yield ctx
    finally:
        reset_request_context(token)


def _stub_session() -> MagicMock:
    """Build a session whose ``call_tool`` returns a stub MCP result."""
    session = MagicMock()
    session.call_tool = AsyncMock(
        return_value=MagicMock(content=[MagicMock(text="ok", type="text")])
    )
    return session


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_resolve_active_workspace_no_context_returns_none() -> None:
    """Without a request context bound, the resolver returns None."""
    assert _resolve_active_workspace() is None


def test_resolve_active_workspace_with_context_returns_path() -> None:
    """A bound context with ``workspace`` in metadata is honored."""
    with _request_workspace("/tmp/foo"):
        assert _resolve_active_workspace() == "/tmp/foo"


def test_resolve_active_workspace_with_empty_value_returns_none() -> None:
    """Empty string is treated as 'unset'."""
    with _request_workspace(""):
        assert _resolve_active_workspace() is None


def test_workspace_aware_tools_set_includes_run_task_variants() -> None:
    """Both agy_run_task and claude_run_task are in the catalogued set."""
    assert "agy_run_task" in _MCP_WORKSPACE_AWARE_TOOLS
    assert "claude_run_task" in _MCP_WORKSPACE_AWARE_TOOLS


# ---------------------------------------------------------------------------
# MCPToolWrapper.execute — auto-fill behavior
# ---------------------------------------------------------------------------


@pytest.fixture
def agy_tool() -> MCPToolWrapper:
    """An MCPToolWrapper wrapping ``agy_run_task`` (workspace-aware)."""
    return MCPToolWrapper(
        session=_stub_session(),
        server_name="agy-mcp-server",
        tool_def=_make_tool_def("agy_run_task"),
        tool_timeout=5,
    )


@pytest.mark.asyncio
async def test_execute_autofills_workspace_path_when_missing(agy_tool: MCPToolWrapper) -> None:
    """Without workspace_path, the active workspace is injected before calling the server."""
    with _request_workspace("/abs/proj"):
        await agy_tool.execute(task="do the thing")

    sent_args = agy_tool._session.call_tool.await_args.kwargs["arguments"]
    assert sent_args["workspace_path"] == "/abs/proj"
    assert sent_args["task"] == "do the thing"


@pytest.mark.asyncio
async def test_execute_does_not_override_explicit_workspace_path(agy_tool: MCPToolWrapper) -> None:
    """An explicit workspace_path wins over the auto-fill."""
    with _request_workspace("/abs/active"):
        await agy_tool.execute(task="x", workspace_path="/abs/explicit")

    sent_args = agy_tool._session.call_tool.await_args.kwargs["arguments"]
    assert sent_args["workspace_path"] == "/abs/explicit"


@pytest.mark.asyncio
async def test_execute_works_without_request_context(agy_tool: MCPToolWrapper) -> None:
    """No request context -> kwargs is sent untouched (caller responsible)."""
    await agy_tool.execute(task="x", workspace_path="/abs/manual")

    sent_args = agy_tool._session.call_tool.await_args.kwargs["arguments"]
    assert sent_args["workspace_path"] == "/abs/manual"


@pytest.mark.asyncio
async def test_execute_does_not_autofill_unknown_tool() -> None:
    """Tools not in ``_MCP_WORKSPACE_AWARE_TOOLS`` are sent unchanged."""
    tool = MCPToolWrapper(
        session=_stub_session(),
        server_name="agy-mcp-server",
        tool_def=_make_tool_def("agy_health"),
        tool_timeout=5,
    )
    with _request_workspace("/abs/active"):
        await tool.execute()

    sent_args = tool._session.call_tool.await_args.kwargs["arguments"]
    assert "workspace_path" not in sent_args


@pytest.mark.asyncio
async def test_execute_treats_empty_string_workspace_path_as_missing(agy_tool: MCPToolWrapper) -> None:
    """Empty string for workspace_path triggers auto-fill (matches the falsy check)."""
    with _request_workspace("/abs/active"):
        await agy_tool.execute(task="x", workspace_path="")

    sent_args = agy_tool._session.call_tool.await_args.kwargs["arguments"]
    assert sent_args["workspace_path"] == "/abs/active"


@pytest.mark.asyncio
async def test_execute_treats_non_string_workspace_path_as_missing(agy_tool: MCPToolWrapper) -> None:
    """A non-string value also triggers auto-fill (defensive: Pydantic may coerce)."""
    with _request_workspace("/abs/active"):
        await agy_tool.execute(task="x", workspace_path=None)

    sent_args = agy_tool._session.call_tool.await_args.kwargs["arguments"]
    assert sent_args["workspace_path"] == "/abs/active"
