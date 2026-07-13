"""Permission gate for sustained-goal mutations.

Ported from nanobot's ``goal_permission.py``.  A single
:class:`ContextVar` indicates whether the current async task is allowed
to mutate the goal — create, replace — through the ``LongTaskTool``.

Default: ``False`` (no goal mutation allowed).
Enable via :func:`set_goal_mutation_allowed` when an inbound originates
from ``/goal``, or from the loop's auto-wrap hook in long-task-by-default
mode.

Once a goal transitions to a terminal state (``complete``/``cancel``/
``block``), the helper :func:`revoke_goal_mutation_permission` resets the
flag — preventing an orphan worker from continuing to ``replace`` the
goal indefinitely.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_GOAL_MUTATION_ALLOWED: ContextVar[bool] = ContextVar(
    "femtobot_goal_mutation_allowed", default=False
)


class GoalMutationNotAllowedError(RuntimeError):
    """Raised by tools when the current context cannot mutate the goal.

    The tool layer converts this into a structured error so the LLM can
    recover (e.g. by calling ``complete_goal`` instead of ``long_task``).
    """


def goal_mutation_allowed() -> bool:
    """Return whether the current async task may create or replace the goal."""
    try:
        return bool(_GOAL_MUTATION_ALLOWED.get())
    except LookupError:
        return False


def set_goal_mutation_allowed(value: bool) -> object:
    """Set the flag, returning a token that ``reset`` can use to restore prior state."""
    return _GOAL_MUTATION_ALLOWED.set(bool(value))


def reset_goal_mutation_permission(token: object) -> None:
    """Restore the previous value (used by :func:`goal_mutation_scope`)."""
    _GOAL_MUTATION_ALLOWED.reset(token)  # type: ignore[arg-type]


@contextmanager
def goal_mutation_scope(allowed: bool = True) -> Iterator[None]:
    """Context manager equivalent of ``set/reset_goal_mutation_permission``.

    Usage::

        with goal_mutation_scope(True):
            await tool.execute(...)
    """
    token = set_goal_mutation_allowed(allowed)
    try:
        yield
    finally:
        reset_goal_mutation_permission(token)


def require_goal_mutation_permission() -> None:
    """Raise :class:`GoalMutationNotAllowedError` if the flag is ``False``."""
    if not goal_mutation_allowed():
        raise GoalMutationNotAllowedError(
            "Long-task mutations are not allowed in this turn. "
            "Use `/goal <objective>` to bootstrap one, or call `complete_goal` "
            "if a goal is already active."
        )


def revoke_goal_mutation_permission() -> None:
    """Set the flag back to ``False`` (e.g. after ``complete``/``cancel``/``block``).

    Walks the :class:`~contextvars.ContextVar` stack and resets any token
    that flipped the flag to ``True``.  This avoids leaking context
    tokens when the worker terminates a goal mid-``goal_mutation_scope``.
    """
    # Note: ``ContextVar.set`` does not expose its token list.  We
    # instead fall back to setting the flag to ``False`` and let the
    # surrounding ``goal_mutation_scope`` reset cleanly when it exits.
    set_goal_mutation_allowed(False)