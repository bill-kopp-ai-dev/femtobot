"""Tests for the per-turn tool schema filter (PR 2.3) and the
by_default command-state hook (PR 2.4).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from femtobot.agent.tool_visibility import (
    complete_goal_visible,
    filter_tool_schemas_for_turn,
    long_task_visible,
)
from femtobot.session.goal_state import GOAL_STATE_KEY


def _schema(name: str) -> dict:
    """Mimic the flat schema layout the ToolRegistry uses internally."""
    return {"name": name, "parameters": {"type": "object", "properties": {}}}


def test_long_task_visible_when_by_default_true():
    cfg = SimpleNamespace(by_default=True, max_goal_rounds=1)
    assert long_task_visible(
        session_metadata={}, message_metadata=None, long_task_config=cfg
    ) is True


def test_long_task_hidden_when_by_default_false_and_no_marker():
    cfg = SimpleNamespace(by_default=False)
    assert long_task_visible(
        session_metadata={}, message_metadata=None, long_task_config=cfg
    ) is False


def test_long_task_visible_when_explicit_goal_requested():
    assert long_task_visible(
        session_metadata={},
        message_metadata={"original_command": "/goal"},
        long_task_config=SimpleNamespace(by_default=False),
    ) is True


def test_long_task_visible_when_implicit_marker_set():
    assert long_task_visible(
        session_metadata={},
        message_metadata={"goal_requested_implicitly": True},
        long_task_config=SimpleNamespace(by_default=False),
    ) is True


def test_complete_goal_visible_only_when_active():
    assert complete_goal_visible(session_metadata={}) is False
    md = {GOAL_STATE_KEY: {"status": "active", "objective": "ship"}}
    assert complete_goal_visible(session_metadata=md) is True
    md = {GOAL_STATE_KEY: {"status": "completed"}}
    assert complete_goal_visible(session_metadata=md) is False


def test_filter_tool_schemas_for_turn_hides_long_task_by_default():
    cfg = SimpleNamespace(by_default=False)
    schemas = [_schema("read_file"), _schema("long_task"), _schema("complete_goal")]
    filtered = filter_tool_schemas_for_turn(
        schemas,
        session_metadata={},
        message_metadata=None,
        long_task_config=cfg,
    )
    names = [s["name"] for s in filtered]
    assert "read_file" in names
    assert "long_task" not in names
    assert "complete_goal" not in names


def test_filter_tool_schemas_for_turn_shows_complete_when_active():
    cfg = SimpleNamespace(by_default=False)
    schemas = [_schema("read_file"), _schema("long_task"), _schema("complete_goal")]
    md = {GOAL_STATE_KEY: {"status": "active", "objective": "ship"}}
    filtered = filter_tool_schemas_for_turn(
        schemas,
        session_metadata=md,
        message_metadata=None,
        long_task_config=cfg,
    )
    names = [s["name"] for s in filtered]
    assert "complete_goal" in names
    assert "long_task" not in names


def test_filter_tool_schemas_for_turn_shows_both_when_by_default_and_active():
    cfg = SimpleNamespace(by_default=True)
    schemas = [_schema("read_file"), _schema("long_task"), _schema("complete_goal")]
    md = {GOAL_STATE_KEY: {"status": "active", "objective": "ship"}}
    filtered = filter_tool_schemas_for_turn(
        schemas,
        session_metadata=md,
        message_metadata=None,
        long_task_config=cfg,
    )
    names = [s["name"] for s in filtered]
    assert "long_task" in names
    assert "complete_goal" in names


def test_filter_tool_schemas_for_turn_preserves_unknown_schemas():
    cfg = SimpleNamespace(by_default=False)
    schemas = [
        _schema("read_file"),
        {"function": {"name": "mcp_query"}, "parameters": {}},
    ]
    filtered = filter_tool_schemas_for_turn(
        schemas, session_metadata={}, message_metadata=None, long_task_config=cfg
    )
    names = [s.get("name") or s.get("function", {}).get("name") for s in filtered]
    assert "read_file" in names
    assert "mcp_query" in names


def test_filter_tool_schemas_for_turn_handles_openai_schema_shape():
    """Real schemas come as ``{function: {name, ...}, type: function}``."""
    cfg = SimpleNamespace(by_default=False)
    schemas = [
        {
            "type": "function",
            "function": {"name": "complete_goal", "parameters": {"type": "object"}},
        }
    ]
    md = {GOAL_STATE_KEY: {"status": "active", "objective": "ship"}}
    filtered = filter_tool_schemas_for_turn(
        schemas, session_metadata=md, message_metadata=None, long_task_config=cfg
    )
    assert len(filtered) == 1
    # hidden when no active goal
    filtered2 = filter_tool_schemas_for_turn(
        schemas, session_metadata={}, message_metadata=None, long_task_config=cfg
    )
    assert filtered2 == []


# PR 2.4 — by_default command-state hook


@pytest.mark.asyncio
async def test_state_command_marks_goal_requested_when_by_default_true(tmp_path):
    """``by_default=true`` flips non-slash inbounds into implicit goal requests."""
    import asyncio

    from femtobot.agent.loop import AgentLoop
    from femtobot.bus.events import InboundMessage
    from femtobot.bus.queue import MessageBus

    # Minimal Provider stub
    class _StubProvider:
        generation = SimpleNamespace(max_tokens=8192)

        def get_default_model(self) -> str:
            return "stub"

        async def chat(self, *args, **kwargs):
            return None

        async def chat_stream(self, *args, **kwargs):
            yield None

    from femtobot.config.schema import LongTaskConfig

    loop = AgentLoop(
        bus=MessageBus(),
        provider=_StubProvider(),
        workspace=tmp_path,
        long_task_config=LongTaskConfig(by_default=True),
    )
    msg = InboundMessage(
        channel="cli",
        sender_id="tester",
        chat_id="chat-1",
        content="Refactor X",
    )
    from femtobot.session.manager import Session

    session = loop.sessions.get_or_create("cli:chat-1")
    from dataclasses import dataclass, field
    from femtobot.agent.loop import TurnContext, TurnState
    import uuid

    @dataclass
    class _Ctx:
        msg: InboundMessage
        session_key: str = "cli:chat-1"
        state: TurnState = TurnState.COMMAND
        turn_id: str = field(default_factory=lambda: uuid.uuid4().hex)
        session: Session | None = None
        history: list = field(default_factory=list)
        initial_messages: list = field(default_factory=list)
        final_content: str | None = None
        tools_used: list = field(default_factory=list)
        all_messages: list = field(default_factory=list)
        stop_reason: str = ""
        had_injections: bool = False

    ctx = _Ctx(msg=msg, session=session)
    # Run the hook — it should mutate ctx.msg.metadata in place.
    next_state = await loop._state_command(ctx)
    # The auto-wrap path now sets only ``goal_requested_implicitly``
    # (the implicit flag) — ``goal_requested`` is reserved for explicit
    # ``/goal`` slash commands so the two predicates stay orthogonal.
    assert ctx.msg.metadata.get("goal_requested") is None
    assert ctx.msg.metadata.get("goal_requested_implicitly") is True
    assert ctx.session.metadata.get("goal_requested_implicitly") is True


@pytest.mark.asyncio
async def test_state_command_does_not_mark_goal_when_by_default_false(tmp_path):
    """Default off — existing behavior preserved."""
    from femtobot.agent.loop import AgentLoop
    from femtobot.bus.events import InboundMessage
    from femtobot.bus.queue import MessageBus

    class _StubProvider:
        generation = SimpleNamespace(max_tokens=8192)

        def get_default_model(self) -> str:
            return "stub"

        async def chat(self, *args, **kwargs):
            return None

        async def chat_stream(self, *args, **kwargs):
            yield None

    loop = AgentLoop(
        bus=MessageBus(),
        provider=_StubProvider(),
        workspace=tmp_path,
        long_task_config=None,  # default: by_default=False
    )
    msg = InboundMessage(
        channel="cli",
        sender_id="tester",
        chat_id="chat-1",
        content="Hello there",
    )
    from femtobot.agent.loop import TurnContext, TurnState
    import uuid
    from dataclasses import dataclass, field

    @dataclass
    class _Ctx:
        msg: InboundMessage
        session_key: str = "cli:chat-1"
        state: TurnState = TurnState.COMMAND
        turn_id: str = field(default_factory=lambda: uuid.uuid4().hex)
        session: object | None = None
        history: list = field(default_factory=list)
        initial_messages: list = field(default_factory=list)
        final_content: str | None = None
        tools_used: list = field(default_factory=list)
        all_messages: list = field(default_factory=list)
        stop_reason: str = ""
        had_injections: bool = False

    ctx = _Ctx(msg=msg, session=None)
    await loop._state_command(ctx)
    assert "goal_requested" not in ctx.msg.metadata
    assert "goal_requested_implicitly" not in ctx.msg.metadata


@pytest.mark.asyncio
async def test_state_command_does_not_mark_when_inbound_is_slash_command(tmp_path):
    """Slash commands keep their original flow even with ``by_default=true``."""
    from femtobot.agent.loop import AgentLoop
    from femtobot.bus.events import InboundMessage
    from femtobot.bus.queue import MessageBus

    class _StubProvider:
        generation = SimpleNamespace(max_tokens=8192)

        def get_default_model(self) -> str:
            return "stub"

        async def chat(self, *args, **kwargs):
            return None

        async def chat_stream(self, *args, **kwargs):
            yield None

    from femtobot.config.schema import LongTaskConfig

    loop = AgentLoop(
        bus=MessageBus(),
        provider=_StubProvider(),
        workspace=tmp_path,
        long_task_config=LongTaskConfig(by_default=True),
    )
    msg = InboundMessage(
        channel="cli",
        sender_id="tester",
        chat_id="chat-1",
        content="/help",
    )
    from femtobot.agent.loop import TurnState
    import uuid
    from dataclasses import dataclass, field

    @dataclass
    class _Ctx:
        msg: InboundMessage
        session_key: str = "cli:chat-1"
        state: TurnState = TurnState.COMMAND
        turn_id: str = field(default_factory=lambda: uuid.uuid4().hex)
        session: object | None = None
        history: list = field(default_factory=list)
        initial_messages: list = field(default_factory=list)
        final_content: str | None = None
        tools_used: list = field(default_factory=list)
        all_messages: list = field(default_factory=list)
        stop_reason: str = ""
        had_injections: bool = False

    session = loop.sessions.get_or_create("cli:chat-1")
    ctx = _Ctx(msg=msg, session=session)
    await loop._state_command(ctx)
    # Slash commands are dispatched by the router and don't need the auto-wrap marker.
    assert "goal_requested_implicitly" not in ctx.msg.metadata