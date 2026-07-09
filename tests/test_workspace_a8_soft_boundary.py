"""Soft workspace boundary regression tests (A8).

Before A8 every workspace violation was a hard-fail (the tool raised and
the agent loop died on the same path three times in a row).  A8 introduces
a soft mode (gated by ``FEMTOBOT_SOFT_WORKSPACE_BOUNDARY``) that converts
the first N violations per session into a recoverable warning string
returned to the LLM.  After N strikes the boundary hard-fails again so a
stuck loop is still killed quickly.
"""

from __future__ import annotations

import pytest

from femtobot.security import workspace_soft_boundary as soft
from femtobot.security.workspace_soft_boundary import (
    is_soft_mode,
    max_strikes,
    record_violation,
    reset_violations,
    violation_count,
)

pytestmark = pytest.mark.security


@pytest.fixture(autouse=True)
def _clean_counters(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the in-process counter between tests so order doesn't matter."""
    monkeypatch.setenv("FEMTOBOT_SOFT_WORKSPACE_BOUNDARY", "0")
    # Wipe any pre-existing counters.
    for key in list(soft._VIOLATION_COUNTS.keys()):  # type: ignore[attr-defined]
        reset_violations(key)
    yield
    for key in list(soft._VIOLATION_COUNTS.keys()):  # type: ignore[attr-defined]
        reset_violations(key)


def test_soft_mode_default_off() -> None:
    """Without the env var, soft mode is off (backward compat)."""
    assert is_soft_mode() is False


def test_soft_mode_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """Setting the env var enables soft mode (A8)."""
    monkeypatch.setenv("FEMTOBOT_SOFT_WORKSPACE_BOUNDARY", "1")
    assert is_soft_mode() is True


def test_max_strikes_default_3() -> None:
    """Default strike limit is 3 (A8)."""
    assert max_strikes() == 3


def test_max_strikes_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """The strike limit is configurable via env var."""
    monkeypatch.setenv("FEMTOBOT_SOFT_WORKSPACE_BOUNDARY_STRIKES", "5")
    assert max_strikes() == 5


def test_max_strikes_floor_at_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-positive values are floored to 1 (a strike limit of 0 is meaningless)."""
    monkeypatch.setenv("FEMTOBOT_SOFT_WORKSPACE_BOUNDARY_STRIKES", "0")
    assert max_strikes() == 1


def test_record_violation_increments() -> None:
    """``record_violation`` increments and returns the new total."""
    key = "websocket:test-workspace"
    assert record_violation(key) == 1
    assert record_violation(key) == 2
    assert record_violation(key) == 3
    assert violation_count(key) == 3


def test_reset_violations() -> None:
    """``reset_violations`` clears the counter for a session (A8)."""
    key = "websocket:test-workspace"
    record_violation(key)
    record_violation(key)
    reset_violations(key)
    assert violation_count(key) == 0
