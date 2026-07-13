"""Helper to decide whether an HTTP request should be admitted as an
``async_goal`` job or processed synchronously.

The decision is pure: given the request body and the loop's
:class:`~femtobot.config.schema.LongTaskConfig`, return one of
``"sync"`` / ``"async_goal"``.  The server uses the result to either
await the agent's full response or return ``202 Accepted`` immediately.
"""

from __future__ import annotations

from typing import Any, Mapping

from femtobot.config.schema import LongTaskApiMode


def should_async_goal(
    request_body: Mapping[str, Any] | None,
    *,
    long_task_config: Any | None,
    has_active_goal: bool,
) -> bool:
    """Return ``True`` when the HTTP layer should admit the request as a job.

    * ``sync`` — never admit; always process synchronously.
    * ``async_goal`` — always admit, even when the inbound is trivial.
    * ``auto`` — admit only when the inbound looks like a long-running
      job (has an explicit ``session_id``, or has an existing active
      goal that the new turn should continue, or the caller passed
      ``objective=``).

    The default fallback is ``False`` so legacy deployments are
    unaffected.
    """
    cfg_mode = LongTaskApiMode.SYNC
    if long_task_config is not None:
        try:
            cfg_mode = long_task_config.api_mode  # type: ignore[attr-defined]
        except AttributeError:
            cfg_mode = LongTaskApiMode.SYNC
    if cfg_mode is LongTaskApiMode.SYNC:
        return False
    if cfg_mode is LongTaskApiMode.ASYNC_GOAL:
        return True
    # Auto
    if not request_body:
        return False
    if request_body.get("objective"):
        return True
    if request_body.get("session_id"):
        return True
    if has_active_goal:
        return True
    return False


def resolve_async_mode(long_task_config: Any | None) -> LongTaskApiMode:
    """Return the configured :class:`LongTaskApiMode` (defaults to SYNC)."""
    if long_task_config is None:
        return LongTaskApiMode.SYNC
    try:
        return long_task_config.api_mode
    except AttributeError:
        return LongTaskApiMode.SYNC


__all__ = ["should_async_goal", "resolve_async_mode"]