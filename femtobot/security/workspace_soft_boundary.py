"""Soft workspace boundary with retry-throttle (A8).

By default, femtobot's filesystem / apply_patch tools *hard-fail* when an
LLM asks them to write outside the active workspace.  This is the safest
behavior, but in long sessions the LLM occasionally re-attempts the same
out-of-workspace target and the user sees a hard crash on every retry.

A8 introduces a *soft* mode (gated by ``FEMTOBOT_SOFT_WORKSPACE_BOUNDARY``)
that converts the first N violations per session into a recoverable
warning.  After N strikes the boundary becomes hard again, so a stuck
agent loop still gets killed quickly.

The default strikes count is 3 per session; after that we escalate back
to the historical hard-fail so the user is not stuck in a loop.  The
counts are process-local — process restart resets the counter, which is
fine because the tool calls themselves are auditable in history.
"""

from __future__ import annotations

import os
import threading
from collections import defaultdict
from typing import Literal

from loguru import logger

_DEFAULT_STRIKES = 3

_BoundaryMode = Literal["hard", "soft"]
_VIOLATION_COUNTS: dict[str, int] = defaultdict(int)
_COUNTS_LOCK = threading.Lock()


def is_soft_mode() -> bool:
    """Return True when soft workspace boundary is enabled (A8).

    Honored env var: ``FEMTOBOT_SOFT_WORKSPACE_BOUNDARY``.  Defaults to
    ``false`` to preserve v0.0.2 behavior.
    """
    raw = os.environ.get("FEMTOBOT_SOFT_WORKSPACE_BOUNDARY", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def max_strikes() -> int:
    """Return the configured strike limit (default 3)."""
    raw = os.environ.get("FEMTOBOT_SOFT_WORKSPACE_BOUNDARY_STRIKES", "").strip()
    if not raw:
        return _DEFAULT_STRIKES
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "Ignoring invalid FEMTOBOT_SOFT_WORKSPACE_BOUNDARY_STRIKES={!r}; using {}",
            raw,
            _DEFAULT_STRIKES,
        )
        return _DEFAULT_STRIKES
    if value < 1:
        return 1
    return value


def record_violation(session_key: str) -> int:
    """Increment the violation counter for *session_key* and return the new total."""
    with _COUNTS_LOCK:
        _VIOLATION_COUNTS[session_key] += 1
        return _VIOLATION_COUNTS[session_key]


def violation_count(session_key: str) -> int:
    with _COUNTS_LOCK:
        return _VIOLATION_COUNTS.get(session_key, 0)


def reset_violations(session_key: str) -> None:
    """Clear the counter for a session (used by tests / session restart)."""
    with _COUNTS_LOCK:
        _VIOLATION_COUNTS.pop(session_key, None)


def should_hard_fail(session_key: str) -> bool:
    """True when the caller should still hard-fail on the next violation."""
    if not is_soft_mode():
        return True
    return violation_count(session_key) >= max_strikes()


def mode() -> _BoundaryMode:
    return "soft" if is_soft_mode() else "hard"
