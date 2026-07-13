"""Per-turn tool-schema visibility for long-task-by-default.

The tools ``long_task`` and ``complete_goal`` must appear in the LLM
prompt under specific conditions:

* ``long_task`` — only when the current turn is allowed to create or
  replace a goal (explicit ``/goal``, ``by_default=true`` auto-wrap, or
  the bootstrap hook).

* ``complete_goal`` — always when there is an active sustained goal in
  the session, even if the current turn was not explicitly a ``/goal``
  invocation.  This guarantees the agent can always finalize a goal.

This module is a pure helper: it operates on the registry's schema
list and returns a new list.  No side effects, no I/O.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from femtobot.session.goal_state import (
    explicit_goal_requested,
    goal_bootstrap_requested,
    sustained_goal_active,
)

_LONG_TASK_NAME = "long_task"
_COMPLETE_GOAL_NAME = "complete_goal"


def _schema_name(schema: Mapping[str, Any]) -> str:
    """Mirror :meth:`ToolRegistry._schema_name` for flat / OpenAI schemas."""
    fn = schema.get("function")
    if isinstance(fn, dict):
        name = fn.get("name")
        if isinstance(name, str):
            return name
    name = schema.get("name")
    return name if isinstance(name, str) else ""


def long_task_visible(
    *,
    session_metadata: Mapping[str, Any] | None,
    message_metadata: Mapping[str, Any] | None,
    long_task_config: Any | None,
) -> bool:
    """True when the LLM should see ``long_task`` in this turn.

    The filter is consulted *only* for non-slash inbounds — slash commands
    return a shortcut outbound via ``cmd_goal`` and skip the runner.  We
    keep the explicit check defensively so the filter is correct in any
    future flow where it does get called for a ``/goal`` turn.
    """
    if goal_bootstrap_requested(message_metadata):
        return True
    if explicit_goal_requested(message_metadata):
        # Slash command path — the goal already exists in metadata; the tool
        # is mostly redundant, but we still surface it so the model can use
        # ``replace`` if needed.
        return True
    if long_task_config is not None and bool(getattr(long_task_config, "by_default", False)):
        # Long task by default — every inbound is a candidate for an
        # implicit goal.  Applied only when neither of the two explicit
        # predicates above already granted visibility.
        return True
    return False


def complete_goal_visible(
    *,
    session_metadata: Mapping[str, Any] | None,
) -> bool:
    """True when ``complete_goal`` should appear — i.e. an active goal exists."""
    return sustained_goal_active(session_metadata)


def filter_tool_schemas_for_turn(
    registry_schemas: Iterable[Mapping[str, Any]],
    *,
    session_metadata: Mapping[str, Any] | None,
    message_metadata: Mapping[str, Any] | None,
    long_task_config: Any | None,
) -> list[Mapping[str, Any]]:
    """Return the subset of tool schemas that the LLM should see this turn.

    Goals of the filter:

    * Hide ``long_task`` when no turn may create/replace the goal.
    * Hide ``complete_goal`` when no active goal exists — surfacing it
      otherwise leads the model to guess the API.
    * Pass through every other tool unchanged (MCP, fs, exec, …).

    The filter is defensive: missing keys or unexpected shapes do not
    cause the helper to raise.
    """
    show_long = long_task_visible(
        session_metadata=session_metadata,
        message_metadata=message_metadata,
        long_task_config=long_task_config,
    )
    show_complete = complete_goal_visible(session_metadata=session_metadata)

    out: list[Mapping[str, Any]] = []
    for schema in registry_schemas:
        name = _schema_name(schema)
        if name == _LONG_TASK_NAME and not show_long:
            continue
        if name == _COMPLETE_GOAL_NAME and not show_complete:
            continue
        out.append(schema)
    return out


__all__ = [
    "filter_tool_schemas_for_turn",
    "long_task_visible",
    "complete_goal_visible",
]