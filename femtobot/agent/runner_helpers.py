"""Helpers that run alongside PydanticAI's agent loop.

Femtobot 1.0 (Phase 4 — scaffold) — the original
``femtobot/agent/runner.py`` implemented a state machine around LLM
calls. PydanticAI's ``Agent`` already provides that state machine;
this file keeps only the femtobot-specific glue:

  - ``persist_tool_result``    — write tool outputs to the session JSONL
  - ``post_run_autocompact``   — run AutoCompact if context is large
  - ``post_run_session_save``  — save the final session state

These helpers are consumed by ``FemtobotAgent`` via an
``on_tool_call`` callback (planned for a future Phase 4 iteration
once ``FemtobotAgent`` becomes the production loop).

The legacy ``femtobot/agent/runner.py`` (1895 LOC) and
``femtobot/agent/loop.py`` (2179 LOC) remain in place: deleting them
in this branch would cascade-break the existing
``cli/commands.py`` integration and the entire 1340-test legacy
suite. The full migration is reserved for a future, dedicated hard
refactor with proper test-parity scaffolding.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from femtobot.agent.deps import FemtobotDeps


async def persist_tool_result(
    deps: "FemtobotDeps",
    tool_name: str,
    args: dict[str, Any],
    result: str,
) -> None:
    """Append a tool call + result to the active session JSONL.

    No-op when the deps do not carry a session. The legacy runner
    keeps a richer behavior (multi-tool batching, truncation);
    PydanticAI's per-tool callback only needs the simplest path.
    """
    if deps.session is None or deps.session_manager is None:
        return
    deps.session.add_message(
        "tool",
        f"```\n{tool_name}({args!r})\n```",
        tool_name=tool_name,
        tool_args=args,
        tool_result=result,
    )
    deps.session_manager.save(deps.session)


async def post_run_autocompact(deps: "FemtobotDeps") -> None:
    """If the session is too large, run AutoCompact."""
    if deps.session is None or deps.session_manager is None:
        return
    # Lazy import — AutoCompact pulls in heavy prompt-template glue
    # that we want kept off the cold-start path.
    from femtobot.agent.autocompact import AutoCompact

    compact = AutoCompact(deps.config)
    if compact.should_run(deps.session):
        compact.run(deps.session)
        deps.session_manager.save(deps.session)


async def post_run_session_save(deps: "FemtobotDeps") -> None:
    """Flush the final session state to disk after a successful run."""
    if deps.session is None or deps.session_manager is None:
        return
    deps.session_manager.save(deps.session)


__all__ = [
    "persist_tool_result",
    "post_run_autocompact",
    "post_run_session_save",
]
