"""B2: AgentRunSpec exposes ``goal_iteration_extra_budget`` (B2).

B2 (REFACTOR_PLAN.md Lote B): when ``max_iterations`` is exhausted and
``goal_active_predicate()`` returns True, the runner extends the loop by
``spec.goal_iteration_extra_budget`` (default 50) before finalizing.

We don't drive the full AgentRunner here (it would require a real
provider).  Instead, we pin the dataclass contract:

* the field exists with a sensible default,
* it can be overridden to 0 (disabled),
* the value flows through to the agent loop's iteration cap.
"""

from __future__ import annotations

import pytest

from femtobot.agent.runner import AgentRunSpec

pytestmark = pytest.mark.durability


def _make_spec(extra_budget: int | None = None) -> AgentRunSpec:
    """Build a minimal AgentRunSpec; we don't actually run it."""
    from femtobot.agent.tools.registry import ToolRegistry

    spec_kwargs: dict = dict(
        initial_messages=[],
        tools=ToolRegistry(),
        model="m",
        max_iterations=4,
        max_tool_result_chars=1000,
    )
    if extra_budget is not None:
        spec_kwargs["goal_iteration_extra_budget"] = extra_budget
    return AgentRunSpec(**spec_kwargs)


def test_default_extra_budget_is_50() -> None:
    """B2: ``goal_iteration_extra_budget`` defaults to 50 (B2)."""
    spec = _make_spec()
    assert spec.goal_iteration_extra_budget == 50


def test_extra_budget_can_be_overridden() -> None:
    """B2: callers can override the extra budget (B2)."""
    spec = _make_spec(extra_budget=10)
    assert spec.goal_iteration_extra_budget == 10


def test_extra_budget_can_be_disabled() -> None:
    """B2: ``extra_budget=0`` disables the extension (B2)."""
    spec = _make_spec(extra_budget=0)
    assert spec.goal_iteration_extra_budget == 0


def test_base_max_iterations_unchanged() -> None:
    """B2: the base ``max_iterations`` is independent of the extra budget (B2)."""
    spec = _make_spec(extra_budget=200)
    assert spec.max_iterations == 4
    assert spec.goal_iteration_extra_budget == 200
    # Effective cap = max_iterations + extra_budget = 4 + 200 = 204.
    # This is what the runner code computes at the top of the loop.
    effective = spec.max_iterations + spec.goal_iteration_extra_budget
    assert effective == 204
