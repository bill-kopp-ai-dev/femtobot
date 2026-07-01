"""Lightweight session status line.

Renders a single-line summary of the current turn using only data already
available on the ``AgentLoop`` (``model``, ``_last_usage``, ``_start_time``).
Shown at the end of each turn in interactive mode and inside ``/status``.

Camada 1 (1.8) do ``FEMTOBOT_CLI_REFACTOR_PLAN.md``.
"""

from __future__ import annotations

import time
from typing import Any, Mapping

from rich.console import RenderableType
from rich.text import Text


def format_tokens(n: int) -> str:
    """Format a token count with thousands separator (e.g. 12,400)."""
    return f"{n:,}"


def format_elapsed(start_time: float, *, now: float | None = None) -> str:
    """Format seconds-since-start as '1.2s' or '1m02.3s' for long durations."""
    elapsed = max((now if now is not None else time.time()) - start_time, 0.0)
    if elapsed < 60:
        return f"{elapsed:.1f}s"
    minutes = int(elapsed // 60)
    seconds = elapsed - minutes * 60
    return f"{minutes}m{seconds:04.1f}s"


def render_session_status_line(
    loop: Any,
    usage: Mapping[str, int] | None = None,
    *,
    show_tokens: bool = True,
    show_elapsed: bool = True,
    now: float | None = None,
) -> RenderableType:
    """Render a one-line status summary for the current turn.

    ``loop`` is duck-typed: we only read ``model``, ``_last_usage``,
    and ``_start_time``. Any missing attribute is silently treated as
    not-available.
    """
    model = getattr(loop, "model", None) or "model"
    used = dict(usage or getattr(loop, "_last_usage", {}) or {})
    start = getattr(loop, "_start_time", None)
    prompt_tokens = int(used.get("prompt_tokens", 0))

    parts: list[tuple[str, str]] = [(f" {model} ", "bold cyan")]
    if show_tokens and prompt_tokens:
        parts.append((" · ", "dim"))
        parts.append((f"{format_tokens(prompt_tokens)} tok in ", "dim"))
    if show_elapsed and isinstance(start, (int, float)):
        parts.append((" · ", "dim"))
        parts.append((f"{format_elapsed(float(start), now=now)} ", "dim"))
    return Text.assemble(*parts)
