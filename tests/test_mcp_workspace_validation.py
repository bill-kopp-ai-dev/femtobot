"""Tests for the MCP workspace_path pre-flight validation layer.

Refs: defensive layer added after observing the
``ValueError: NOT_ALLOWED: workspace_path is outside allowed roots`` failure
mode during femtobot↔agy/claude smoke tests. Goal: catch policy violations on
the client side with an actionable message, instead of letting the server
return a raw ``ValueError``.

These tests cover three layers:

1. ``_extract_allowed_roots`` — pure parser of the ``*_MCP_ALLOWED_ROOTS`` env
   var (defensive: never raises; tolerates malformed input).
2. ``_validate_workspace_against_allowed_roots`` — pure path-membership check
   honoring the ``"/"`` escape hatch and empty-policy pass-through.
3. ``MCPToolWrapper.execute`` — integration: when the server has known roots
   and the caller passes an out-of-policy ``workspace_path``, the wrapper
   short-circuits with a clear message instead of round-tripping.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from femtobot.agent.tools.context import (
    RequestContext,
    bind_request_context,
    reset_request_context,
)
from femtobot.agent.tools.mcp import (
    _extract_allowed_roots,
    _validate_workspace_against_allowed_roots,
    MCPToolWrapper,
)


# ---------------------------------------------------------------------------
# _extract_allowed_roots
# ---------------------------------------------------------------------------


def test_extract_allowed_roots_parses_agy_mcp_env() -> None:
    """``AGY_MCP_ALLOWED_ROOTS='["/foo","/bar"]'`` parses into two Paths."""
    env = {"AGY_MCP_ALLOWED_ROOTS": '["/foo", "/bar"]'}
    roots = _extract_allowed_roots(env)
    assert [str(p) for p in roots] == ["/foo", "/bar"]


def test_extract_allowed_roots_parses_claude_mcp_env() -> None:
    """``CLAUDE_MCP_ALLOWED_ROOTS='["/foo"]'`` parses into one Path."""
    env = {"CLAUDE_MCP_ALLOWED_ROOTS": '["/foo"]'}
    roots = _extract_allowed_roots(env)
    assert [str(p) for p in roots] == ["/foo"]


def test_extract_allowed_roots_parses_bare_allowed_roots_key() -> None:
    """A bare ``ALLOWED_ROOTS`` key (no prefix) also matches the pattern."""
    env = {"ALLOWED_ROOTS": '["/x", "/y"]'}
    roots = _extract_allowed_roots(env)
    assert [str(p) for p in roots] == ["/x", "/y"]


def test_extract_allowed_roots_empty_when_env_is_none() -> None:
    """No env -> empty roots."""
    assert _extract_allowed_roots(None) == []


def test_extract_allowed_roots_empty_when_no_matching_key() -> None:
    """Env without any ALLOWED_ROOTS key -> empty roots."""
    env = {"PATH": "/usr/bin", "HOME": "/root"}
    assert _extract_allowed_roots(env) == []


def test_extract_allowed_roots_handles_malformed_json() -> None:
    """A malformed JSON value is logged-and-ignored; never raises."""
    env = {"AGY_MCP_ALLOWED_ROOTS": "not json"}
    assert _extract_allowed_roots(env) == []


def test_extract_allowed_roots_handles_non_list_json() -> None:
    """A valid JSON value that isn't a list -> empty roots."""
    env = {"AGY_MCP_ALLOWED_ROOTS": '{"foo": "/bar"}'}
    assert _extract_allowed_roots(env) == []


def test_extract_allowed_roots_skips_non_string_entries() -> None:
    """Non-string entries inside the list are dropped (defensive)."""
    env = {"AGY_MCP_ALLOWED_ROOTS": '["/ok", 42, null, "/also-ok"]'}
    roots = _extract_allowed_roots(env)
    assert [str(p) for p in roots] == ["/ok", "/also-ok"]


def test_extract_allowed_roots_stops_after_first_match() -> None:
    """When multiple ALLOWED_ROOTS keys exist, the first wins (deterministic)."""
    env = {
        "AGY_MCP_ALLOWED_ROOTS": '["/primary"]',
        "CLAUDE_MCP_ALLOWED_ROOTS": '["/secondary"]',
    }
    roots = _extract_allowed_roots(env)
    # The parser iterates the dict; the first matched key is returned.
    # The actual first depends on insertion order, which we control here.
    assert len(roots) == 1
    assert str(roots[0]) in {"/primary", "/secondary"}


# ---------------------------------------------------------------------------
# _validate_workspace_against_allowed_roots
# ---------------------------------------------------------------------------


def test_validate_workspace_returns_none_when_inside_root(tmp_path: Path) -> None:
    """Path inside an allowed root -> valid (returns None)."""
    allowed = [tmp_path]
    sub = tmp_path / "sub"
    sub.mkdir()
    assert _validate_workspace_against_allowed_roots(str(sub), allowed) is None


def test_validate_workspace_returns_none_when_equal_to_root(tmp_path: Path) -> None:
    """Path equal to an allowed root -> valid (boundary case)."""
    allowed = [tmp_path]
    assert _validate_workspace_against_allowed_roots(str(tmp_path), allowed) is None


def test_validate_workspace_returns_error_when_outside_root(tmp_path: Path) -> None:
    """Path outside any allowed root -> error message naming the path and roots."""
    allowed = [tmp_path / "allowed"]
    outside = tmp_path / "outside"
    outside.mkdir()
    err = _validate_workspace_against_allowed_roots(str(outside), allowed)
    assert err is not None
    assert str(outside) in err
    assert "ALLOWED_ROOTS" in err
    assert "Do NOT retry" in err  # actionable hint


def test_validate_workspace_prefix_does_not_match(tmp_path: Path) -> None:
    """A path whose *string* starts with a root must not match a sibling path.

    Defends against naive ``startswith`` without trailing-separator. E.g.
    ``/foo`` should NOT match ``/foobar/baz`` as an allowed descendant.
    """
    foo = tmp_path / "foo"
    foo.mkdir()
    foobar = tmp_path / "foobar"
    foobar.mkdir()
    err = _validate_workspace_against_allowed_roots(str(foobar / "baz"), [foo])
    assert err is not None


def test_validate_workspace_returns_none_when_root_is_slash() -> None:
    """``["/"]`` is the documented escape hatch -> always valid."""
    err = _validate_workspace_against_allowed_roots("/anything/at/all", [Path("/")])
    assert err is None


def test_validate_workspace_returns_none_when_no_policy() -> None:
    """Empty ``allowed_roots`` -> no client-side validation; defer to server."""
    err = _validate_workspace_against_allowed_roots("/anything", [])
    assert err is None


def test_validate_workspace_error_message_includes_actionable_hint() -> None:
    """The error message must tell the caller what to do instead of retrying."""
    allowed = [Path("/allowed")]
    err = _validate_workspace_against_allowed_roots("/not/allowed", allowed)
    assert err is not None
    assert "omit" in err.lower() or "subdirectory" in err.lower()


# ---------------------------------------------------------------------------
# MCPToolWrapper.execute — pre-flight short-circuit
# ---------------------------------------------------------------------------


def _make_tool_def(name: str) -> MagicMock:
    """Minimal stub matching the ``mcp.types.Tool`` interface."""
    tool_def = MagicMock()
    tool_def.name = name
    tool_def.description = "stub"
    tool_def.inputSchema = {
        "type": "object",
        "properties": {},
        "required": [],
    }
    return tool_def


def _stub_session() -> MagicMock:
    """Session whose ``call_tool`` returns a stub MCP result with a real
    ``TextContent`` block (so the wrapper can extract ``.text`` cleanly).
    """
    from mcp import types

    block = types.TextContent(type="text", text="ok")
    session = MagicMock()
    session.call_tool = AsyncMock(
        return_value=MagicMock(content=[block])
    )
    return session


@contextmanager
def _no_request_context() -> Any:
    """Ensure no request context is bound (so auto-fill doesn't kick in)."""
    from femtobot.agent.tools.context import current_request_context

    # No bind -> current_request_context() returns None by default.
    assert current_request_context() is None
    yield


@pytest.fixture
def agy_tool_with_roots(tmp_path: Path) -> MCPToolWrapper:
    """An ``agy_run_task`` wrapper with one allowed root at ``tmp_path``."""
    return MCPToolWrapper(
        session=_stub_session(),
        server_name="agy-mcp-server",
        tool_def=_make_tool_def("agy_run_task"),
        tool_timeout=5,
        allowed_roots=[tmp_path],
    )


@pytest.mark.asyncio
async def test_execute_blocks_workspace_path_outside_allowed_roots(
    agy_tool_with_roots: MCPToolWrapper, tmp_path: Path
) -> None:
    """When the caller passes a workspace_path outside the server's roots,
    the wrapper short-circuits with an actionable message and never calls
    ``session.call_tool``.
    """
    # ``tmp_path`` is the only allowed root; pick a sibling outside of it.
    outside = tmp_path.parent / "definitely-not-allowed"
    outside.mkdir(exist_ok=True)

    with _no_request_context():
        result = await agy_tool_with_roots.execute(
            task="x",
            workspace_path=str(outside),
        )

    assert "pre-flight" in result.lower() or "blocked" in result.lower()
    assert str(outside) in result
    # The server was never contacted.
    agy_tool_with_roots._session.call_tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_passes_workspace_path_inside_allowed_roots(
    agy_tool_with_roots: MCPToolWrapper, tmp_path: Path
) -> None:
    """A workspace_path inside the server's roots is forwarded to the server."""
    inside = tmp_path / "inside"
    inside.mkdir()

    with _no_request_context():
        result = await agy_tool_with_roots.execute(
            task="x",
            workspace_path=str(inside),
        )

    assert result == "ok"
    sent_args = agy_tool_with_roots._session.call_tool.await_args.kwargs["arguments"]
    assert sent_args["workspace_path"] == str(inside)
    assert sent_args["task"] == "x"


@pytest.mark.asyncio
async def test_execute_skips_validation_when_allowed_roots_empty() -> None:
    """When the wrapper was constructed without an ``allowed_roots`` policy
    (e.g. server didn't declare one in env), the wrapper does NOT pre-flight
    validate — it defers to the server's own enforcement.
    """
    tool = MCPToolWrapper(
        session=_stub_session(),
        server_name="agy-mcp-server",
        tool_def=_make_tool_def("agy_run_task"),
        tool_timeout=5,
        # allowed_roots omitted -> empty
    )

    with _no_request_context():
        # Any path is accepted client-side when no policy is known.
        result = await tool.execute(task="x", workspace_path="/anywhere")

    assert result == "ok"
    tool._session.call_tool.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_skips_validation_for_non_workspace_aware_tool(
    tmp_path: Path,
) -> None:
    """Tools NOT in ``_MCP_WORKSPACE_AWARE_TOOLS`` never validate workspace_path."""
    tool = MCPToolWrapper(
        session=_stub_session(),
        server_name="agy-mcp-server",
        tool_def=_make_tool_def("agy_health"),  # not workspace-aware
        tool_timeout=5,
        allowed_roots=[tmp_path],
    )

    with _no_request_context():
        # No workspace_path kwarg is passed by health-style tools anyway, but
        # even if a stray one slipped through, the wrapper ignores it.
        result = await tool.execute()

    assert result == "ok"
    tool._session.call_tool.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_with_slash_wildcard_root_does_not_block(tmp_path: Path) -> None:
    """``["/"]`` escape hatch -> client-side validation is bypassed."""
    tool = MCPToolWrapper(
        session=_stub_session(),
        server_name="agy-mcp-server",
        tool_def=_make_tool_def("agy_run_task"),
        tool_timeout=5,
        allowed_roots=[Path("/")],
    )

    with _no_request_context():
        result = await tool.execute(task="x", workspace_path="/literally/anywhere")

    assert result == "ok"
    tool._session.call_tool.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_pre_flight_does_not_override_autofill(
    agy_tool_with_roots: MCPToolWrapper, tmp_path: Path
) -> None:
    """Auto-fill runs *before* pre-flight validation, so an active workspace
    inside the allowed roots is accepted even when the caller omitted
    ``workspace_path`` (this is the success path for the original bug).
    """
    inside = tmp_path / "active"
    inside.mkdir()
    ctx = RequestContext(channel="cli", chat_id="c1", metadata={"workspace": str(inside)})
    token = bind_request_context(ctx)
    try:
        result = await agy_tool_with_roots.execute(task="x")
    finally:
        reset_request_context(token)

    assert result == "ok"
    sent_args = agy_tool_with_roots._session.call_tool.await_args.kwargs["arguments"]
    assert sent_args["workspace_path"] == str(inside)
