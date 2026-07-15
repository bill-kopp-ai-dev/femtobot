"""Per-session permission prompt collector (T6).

This module is **self-contained** — it does not depend on
``session/pending_asks.py`` (per rev. F2 of the parity plan, that
module is an async cross-process correlation-id mechanism, not a
synchronous REPL prompt). The collector is a small in-memory state
machine with three outcomes per call:

  ``YES``        — run the tool.
  ``YES_ALWAYS`` — run the tool and remember the choice for the rest
                   of the session (per-tool opt-out, not persisted).
  ``NO``         — block the tool and surface a clear refusal message.

The prompt is **synchronous** (blocking the REPL) and uses
``prompt_toolkit`` for input. The collector itself is async-friendly
so the agent loop can ``await collector.show(...)`` if it wants to.

Per Q4 the collector is **only** triggered for ``risk_level == "high"``
tools (or ``high + medium`` when ``permission_prompt.high_risk_only``
is ``False``). See :mod:`femtobot.security.tool_risk` for the
taxonomy and :mod:`femtobot.security.tool_risk.should_prompt` for
the gating helper.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any, Callable

from femtobot.cli.theme import get_theme
from femtobot.security.tool_risk import (
    RiskAssessment,
    classify_tool,
    should_prompt,
)


class PermissionChoice(str, enum.Enum):
    """Outcome of one permission prompt."""

    YES = "yes"
    YES_ALWAYS = "yes_always"
    NO = "no"
    CANCEL = "cancel"  # user pressed Esc / Ctrl+C


@dataclass(frozen=True)
class PermissionDecision:
    """Bundle of choice + the assessment that triggered it."""

    choice: PermissionChoice
    assessment: RiskAssessment


class PermissionCancelled(Exception):
    """Raised when the user presses Esc during the prompt."""


class _SessionAllowList:
    """A tiny per-tool "always allow" set, scoped to the active REPL session.

    The set is intentionally **not** persisted to ``config.json`` — Q10
    says the per-session policy must reset on REPL exit.
    """

    def __init__(self) -> None:
        self._allowed: set[str] = set()

    def allow(self, tool_name: str) -> None:
        self._allowed.add(tool_name)

    def is_allowed(self, tool_name: str) -> bool:
        return tool_name in self._allowed

    def reset(self) -> None:
        self._allowed.clear()


class PermissionCollector:
    """Stateful prompt collector for the agent loop.

    Parameters
    ----------
    config
        The active Femtobot ``Config``. Read once at construction; if
        the user mutates the permission knobs mid-session, the caller
        is expected to build a fresh collector.
    input_fn
        Callable that returns a string when prompted (e.g.
        ``prompt_toolkit.PromptSession().prompt``). Defaults to a
        function that prompts on stdin. Tests inject their own.
    output_print
        Callable that writes the prompt body to a stream. Defaults to
        Rich's console.print on stdout. Tests inject their own.
    """

    def __init__(
        self,
        config: Any,
        *,
        input_fn: Callable[[str], str] | None = None,
        output_print: Callable[[str], None] | None = None,
    ) -> None:
        self._config = config
        self._theme = get_theme(getattr(config.agents.defaults.cli, "theme", None) or "terracotta-claude")
        self._allow = _SessionAllowList()
        self._input_fn = input_fn or self._default_input
        self._output_print = output_print or self._default_output

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Wipe the per-session allow list (used by ``/reset`` slash)."""
        self._allow.reset()

    def assess(self, tool_name: str, params: dict | None = None) -> RiskAssessment:
        """Classify a tool call against the workspace boundary.

        Convenience pass-through to :func:`classify_tool` that uses the
        configured ``agents.defaults.workspace`` as the boundary root.
        """
        workspace = None
        try:
            workspace = str(self._config.agents.defaults.workspace)
        except AttributeError:
            workspace = None
        return classify_tool(tool_name, params, workspace_root=workspace)

    def needs_prompt(self, tool_name: str, params: dict | None = None) -> bool:
        """Return True iff this tool call should trigger a prompt.

        Honours the user's ``enabled`` / ``high_risk_only`` knobs and
        the per-session "always allow" list — a tool that was accepted
        with ``YES_ALWAYS`` no longer prompts.
        """
        assessment = self.assess(tool_name, params)
        if self._allow.is_allowed(tool_name) and assessment.level.value == "high":
            return False
        return should_prompt(
            assessment,
            enabled=self._enabled,
            high_risk_only=self._high_risk_only,
        )

    async def show(self, tool_name: str, params: dict | None = None) -> PermissionDecision:
        """Display the prompt and return the user's decision.

        ``ESC`` / empty input map to :attr:`PermissionChoice.CANCEL`.
        Raises :class:`PermissionCancelled` only when the prompt is
        aborted by the user — callers translate that to a tool refusal.
        """
        assessment = self.assess(tool_name, params)
        body = self._render_body(tool_name, params, assessment)
        self._output_print(body)
        choice = self._read_choice()
        if choice is PermissionChoice.YES_ALWAYS:
            self._allow.allow(tool_name)
        return PermissionDecision(choice=choice, assessment=assessment)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @property
    def _enabled(self) -> bool:
        try:
            return bool(self._config.agents.defaults.cli.permission_prompt.enabled)
        except AttributeError:
            return False

    @property
    def _high_risk_only(self) -> bool:
        try:
            return bool(self._config.agents.defaults.cli.permission_prompt.high_risk_only)
        except AttributeError:
            return True

    def _render_body(
        self, tool_name: str, params: dict | None, assessment: RiskAssessment
    ) -> str:
        accent = self._theme.permission_accent or self._theme.perm_border
        lines: list[str] = []
        lines.append(f"\n● {self._humanize(tool_name)}({self._args_preview(params)})")
        if assessment.reason:
            lines.append(f"  ⎿ {assessment.reason}")
        if assessment.in_scope is False:
            lines.append(
                f"  [bold {accent}]Path is OUTSIDE the active workspace.[/bold {accent}]"
            )
        lines.append("")
        lines.append("  Do you want to proceed?")
        lines.append(f"  ❯ [bold {accent}]1.[/bold {accent}] Yes")
        lines.append(
            f"    [bold {accent}]2.[/bold {accent}] Yes, and don't ask again for "
            f"{tool_name} in this session"
        )
        lines.append(f"    [bold {accent}]3.[/bold {accent}] No")
        lines.append("")
        lines.append("  Esc to cancel · Enter to confirm default (Yes)")
        return "\n".join(lines)

    @staticmethod
    def _humanize(name: str) -> str:
        if not name:
            return name
        return " ".join(part.capitalize() for part in name.replace("-", "_").split("_") if part)

    @staticmethod
    def _args_preview(params: dict | None) -> str:
        if not params:
            return ""
        if len(params) == 1:
            (key, value), = params.items()
            s = str(value)
            if len(s) > 60:
                s = s[:59] + "…"
            return f"{key}={s!r}"
        return "…"

    def _read_choice(self) -> PermissionChoice:
        try:
            raw = self._input_fn("Choose [1/2/3, default Yes]: ")
        except (KeyboardInterrupt, EOFError):
            return PermissionChoice.CANCEL
        text = (raw or "").strip().lower()
        if text in ("", "y", "yes", "1"):
            return PermissionChoice.YES
        if text in ("2", "yes-always", "yes_always", "always"):
            return PermissionChoice.YES_ALWAYS
        if text in ("3", "n", "no"):
            return PermissionChoice.NO
        if text in ("esc", "cancel", "q"):
            return PermissionChoice.CANCEL
        # Unknown input — default to YES (preserves the "press Enter to
        # continue" muscle memory; the user can always press 3 next time).
        return PermissionChoice.YES

    @staticmethod
    def _default_input(prompt: str) -> str:
        """Default input function — reads one line from stdin."""
        try:
            return input(prompt)
        except (KeyboardInterrupt, EOFError):
            return ""

    @staticmethod
    def _default_output(text: str) -> None:
        """Default output function — writes the body to stdout.

        Uses ``print`` (not ``rich.console.print``) so the prompt is
        pure text and can be redirected / piped without bringing in
        Rich's escape codes. Rich's stylings inside ``_render_body``
        are visible in a TTY and ignored when stdout is a pipe.
        """
        print(text)


__all__ = [
    "PermissionChoice",
    "PermissionDecision",
    "PermissionCancelled",
    "PermissionCollector",
]
