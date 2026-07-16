"""Regression test for a bug introduced alongside the phantom-continuation
fix in ``AgentLoop._state_run``/``_state_save``.

``_state_run`` was fixed to only call ``maybe_continue_turn`` (which sets
``INTERNAL_CONTINUATION_PENDING_META = True`` on ``ctx.msg.metadata``) when
``stop_reason == "max_iterations"``, and to clear the flag for every other
stop reason. That fix is correct on its own.

But ``_state_save`` — which the state machine always transitions to
directly after ``_state_run`` (``(TurnState.RUN, "ok"): TurnState.SAVE``,
see ``femtobot/agent/loop.py``) — was *also* given an unconditional
``ctx.msg.metadata.pop(INTERNAL_CONTINUATION_PENDING_META, None)``. That
erases the flag ``_state_run`` just set for the legitimate
``max_iterations`` continuation case, one state transition later in the
same turn. Downstream, ``run()``'s dispatch loop checks
``internal_continuation_pending(msg.metadata)`` to decide whether to fire
``turn_completed`` / mark the session idle — with the flag always erased,
those fire prematurely while an internal continuation slice is still
queued to run.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

# ``ToolsConfig`` declares ``web: WebToolsConfig`` as a forward ref and
# only calls ``ToolsConfig.model_rebuild()`` after importing the tool
# config classes inside
# ``femtobot/config/schema.py::try _resolve_tool_config_refs()``.
# That top-level call is wrapped in a broad ``except ImportError: pass``,
# which silently swallows the failure when an early collection-order
# import doesn't reach the tool config modules yet — leaving ``ToolsConfig``
# in a mock-validator state where every ``ToolsConfig()`` instantiation
# raises ``PydanticUserError: ToolsConfig is not fully defined``. The fix
# is to resolve the refs explicitly the first time we need them in this
# file (see ``_make_loop`` below).
from femtobot.agent.loop import AgentLoop, TurnContext, TurnState
from femtobot.bus.events import InboundMessage
from femtobot.bus.queue import MessageBus
from femtobot.session.goal_state import GOAL_STATE_KEY
from femtobot.session.turn_continuation import INTERNAL_CONTINUATION_PENDING_META


class _StubProvider:
    generation = SimpleNamespace(max_tokens=8192)

    def get_default_model(self) -> str:
        return "stub"

    async def chat(self, *args, **kwargs):
        return None

    async def chat_stream(self, *args, **kwargs):
        yield None


def _make_loop(tmp_path):
    # See module-level comment: ``ToolsConfig`` is a forward-ref model that
    # needs ``_resolve_tool_config_refs()`` to have run before instantiation.
    from femtobot.config.schema import _resolve_tool_config_refs

    _resolve_tool_config_refs()
    return AgentLoop(
        bus=MessageBus(),
        provider=_StubProvider(),
        workspace=tmp_path,
    )


@pytest.mark.asyncio
async def test_state_save_preserves_continuation_pending_flag(tmp_path):
    loop = _make_loop(tmp_path)
    session = loop.sessions.get_or_create("cli:chat-1")
    session.metadata[GOAL_STATE_KEY] = {"status": "active", "objective": "ship"}

    msg = InboundMessage(
        channel="cli",
        sender_id="tester",
        chat_id="chat-1",
        content="continue the goal",
        metadata={INTERNAL_CONTINUATION_PENDING_META: True},
    )
    ctx = TurnContext(
        msg=msg,
        session_key="cli:chat-1",
        state=TurnState.SAVE,
        turn_id=uuid.uuid4().hex,
        session=session,
        stop_reason="max_iterations",
        final_content="",
        suppress_response=True,
        all_messages=[{"role": "user", "content": "continue the goal"}],
    )

    await loop._state_save(ctx)

    assert ctx.msg.metadata.get(INTERNAL_CONTINUATION_PENDING_META) is True, (
        "_state_save must not erase the pending-continuation flag that "
        "_state_run just set for a legitimate max_iterations continuation"
    )


@pytest.mark.asyncio
async def test_state_save_does_not_reintroduce_flag_when_absent(tmp_path):
    """Sanity check: _state_save must not itself *set* the flag either."""
    loop = _make_loop(tmp_path)
    session = loop.sessions.get_or_create("cli:chat-2")

    msg = InboundMessage(
        channel="cli",
        sender_id="tester",
        chat_id="chat-2",
        content="hello",
        metadata={},
    )
    ctx = TurnContext(
        msg=msg,
        session_key="cli:chat-2",
        state=TurnState.SAVE,
        turn_id=uuid.uuid4().hex,
        session=session,
        stop_reason="completed",
        final_content="hi there",
        all_messages=[{"role": "assistant", "content": "hi there"}],
    )

    await loop._state_save(ctx)

    assert INTERNAL_CONTINUATION_PENDING_META not in ctx.msg.metadata
