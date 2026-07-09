"""B6: ``/goal complete`` slash command marks active goal as completed (B6).

B6 (REFACTOR_PLAN.md Lote B) introduces a new ``/goal complete [recap]``
slash command.  It mutates ``ctx.session.metadata[GOAL_STATE_KEY]`` so
that ``sustained_goal_active`` flips to False, the runner wall timeout
falls back to ``FEMTOBOT_LLM_TIMEOUT_S``, and the recap is preserved
on the goal blob.
"""

from __future__ import annotations

import pytest

from femtobot.session.goal_state import GOAL_STATE_KEY

pytestmark = pytest.mark.durability


def _make_session(metadata: dict | None = None) -> object:
    """Tiny stand-in for a Session object — just exposes ``metadata``."""
    from types import SimpleNamespace

    return SimpleNamespace(metadata=dict(metadata or {}))


def _make_ctx(args: str, session: object | None) -> object:
    """Build a minimal CommandContext stand-in."""
    from types import SimpleNamespace

    msg = SimpleNamespace(
        channel="cli",
        chat_id="chat-1",
        metadata={"render_as": "text"},
    )
    return SimpleNamespace(args=args, msg=msg, session=session)


async def test_goal_complete_marks_active_goal_completed() -> None:
    """B6: ``/goal complete`` flips ``status`` from ``active`` to ``completed`` (B6)."""
    from femtobot.command.builtin import cmd_goal_complete

    session = _make_session(
        {GOAL_STATE_KEY: {"status": "active", "objective": "ship v0.0.4"}}
    )
    ctx = _make_ctx("", session)
    out = await cmd_goal_complete(ctx)
    assert out is not None
    assert "Goal marked complete" in (out.content or "")
    # The session metadata must now report status=completed.
    blob = session.metadata[GOAL_STATE_KEY]
    assert blob["status"] == "completed"
    assert "completed_at" in blob


async def test_goal_complete_records_recap() -> None:
    """B6: a recap argument is stored on the goal blob (B6)."""
    from femtobot.command.builtin import cmd_goal_complete

    session = _make_session(
        {GOAL_STATE_KEY: {"status": "active", "objective": "ship v0.0.4"}}
    )
    ctx = _make_ctx("shipped to PyPI in 3 PRs", session)
    await cmd_goal_complete(ctx)
    blob = session.metadata[GOAL_STATE_KEY]
    assert blob["recap"] == "shipped to PyPI in 3 PRs"


async def test_goal_complete_without_active_goal_refuses() -> None:
    """B6: calling ``/goal complete`` with no active goal is a no-op reply (B6)."""
    from femtobot.command.builtin import cmd_goal_complete

    session = _make_session({})
    ctx = _make_ctx("", session)
    out = await cmd_goal_complete(ctx)
    assert out is not None
    assert "No active goal" in (out.content or "")


async def test_goal_complete_without_session() -> None:
    """B6: ``/goal complete`` outside a session is a no-op reply (B6)."""
    from femtobot.command.builtin import cmd_goal_complete

    ctx = _make_ctx("", session=None)
    out = await cmd_goal_complete(ctx)
    assert out is not None
    assert "No active session" in (out.content or "")


async def test_sustained_goal_active_flips_to_false_after_complete() -> None:
    """B6: ``sustained_goal_active`` returns False after ``/goal complete`` (B6)."""
    from femtobot.command.builtin import cmd_goal_complete
    from femtobot.session.goal_state import sustained_goal_active

    session = _make_session(
        {GOAL_STATE_KEY: {"status": "active", "objective": "ship v0.0.4"}}
    )
    # Sanity: goal is active before the command runs.
    assert sustained_goal_active(session.metadata) is True

    ctx = _make_ctx("", session)
    await cmd_goal_complete(ctx)

    assert sustained_goal_active(session.metadata) is False
