"""Tests for ``femtobot.cli.permission_prompt`` (T6).

Covers:

  * ``needs_prompt`` correctly filters by ``enabled`` and ``high_risk_only``.
  * ``YES`` → run, no session allow-list entry.
  * ``YES_ALWAYS`` → run, plus the tool is added to the per-session list.
  * ``NO`` → block.
  * ``CANCEL`` (Esc / Ctrl+C) → block.
  * The prompt body renders the tool name, args, and reason.
  * ``high_risk_only=False`` also surfaces ``MEDIUM`` tools.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from femtobot.cli.permission_prompt import (
    PermissionChoice,
    PermissionCollector,
    PermissionDecision,
)
from femtobot.config.schema import Config


def _make_config(*, enabled: bool = True, high_risk_only: bool = True) -> Config:
    return Config(
        agents={
            "defaults": {
                "workspace": "~/femtobot",
                "cli": {
                    "permission_prompt": {
                        "enabled": enabled,
                        "high_risk_only": high_risk_only,
                    },
                },
            },
        }
    )


def _make_collector(
    config: Config,
    answers: list[str],
    captured: list[str] | None = None,
) -> PermissionCollector:
    """Build a collector whose input is fed from a fixed list of answers
    and whose output is appended to ``captured`` (if provided)."""

    def fake_input(prompt: str) -> str:
        if captured is not None:
            captured.append(prompt)
        if not answers:
            return ""
        return answers.pop(0)

    return PermissionCollector(
        config,
        input_fn=fake_input,
        output_print=captured.append if captured is not None else (lambda _: None),
    )


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# needs_prompt gating (Q4)
# ---------------------------------------------------------------------------


def test_needs_prompt_disabled_never_prompts() -> None:
    cfg = _make_config(enabled=False)
    c = _make_collector(cfg, [])
    assert c.needs_prompt("exec", {"command": "rm -rf /"}) is False


def test_needs_prompt_high_risk_only_triggers_for_high() -> None:
    cfg = _make_config(enabled=True, high_risk_only=True)
    c = _make_collector(cfg, [])
    assert c.needs_prompt("exec", {"command": "ls"}) is True
    assert c.needs_prompt("long_task", {"objective": "do X"}) is True


def test_needs_prompt_high_risk_only_skips_medium() -> None:
    cfg = _make_config(enabled=True, high_risk_only=True)
    c = _make_collector(cfg, [])
    assert c.needs_prompt("web_fetch", {"url": "https://example.com"}) is False
    # Use a path that resolves INSIDE the configured workspace. The
    # boundary check is path-resolution based, not string-prefix.
    inside = str(Path("~/femtobot/inside.py").expanduser().resolve())
    assert c.needs_prompt("write_file", {"path": inside}) is False


def test_needs_prompt_high_risk_only_false_includes_medium() -> None:
    cfg = _make_config(enabled=True, high_risk_only=False)
    c = _make_collector(cfg, [])
    assert c.needs_prompt("web_fetch", {"url": "https://example.com"}) is True


def test_needs_prompt_low_tools_never_prompt() -> None:
    cfg = _make_config(enabled=True, high_risk_only=False)
    c = _make_collector(cfg, [])
    assert c.needs_prompt("read_file", {"path": "x.py"}) is False
    assert c.needs_prompt("web_search", {"query": "x"}) is False


# ---------------------------------------------------------------------------
# show() — choice mapping
# ---------------------------------------------------------------------------


def test_show_yes_runs_tool() -> None:
    cfg = _make_config(enabled=True, high_risk_only=True)
    captured: list[str] = []
    c = _make_collector(cfg, ["1"], captured)
    decision = _run(c.show("exec", {"command": "ls"}))
    assert decision.choice is PermissionChoice.YES
    assert "Exec" in captured[0]  # the prompt body contains the tool name


def test_show_yes_always_persists_in_session() -> None:
    cfg = _make_config(enabled=True, high_risk_only=True)
    c = _make_collector(cfg, ["2"])
    decision = _run(c.show("exec", {"command": "ls"}))
    assert decision.choice is PermissionChoice.YES_ALWAYS
    # Next call no longer prompts — the session allow-list absorbs it.
    assert c.needs_prompt("exec", {"command": "ls"}) is False


def test_show_yes_always_persists_for_medium_risk_tool() -> None:
    """Regression test: the allow-list bypass used to be gated on
    ``assessment.level == HIGH``, so "Yes, always" silently never took
    effect for a tool that stayed MEDIUM (e.g. ``web_fetch`` when
    ``high_risk_only=False`` surfaces MEDIUM tools too)."""
    cfg = _make_config(enabled=True, high_risk_only=False)
    c = _make_collector(cfg, ["2"])
    assert c.needs_prompt("web_fetch", {"url": "https://example.com"}) is True
    decision = _run(c.show("web_fetch", {"url": "https://example.com"}))
    assert decision.choice is PermissionChoice.YES_ALWAYS
    assert c.needs_prompt("web_fetch", {"url": "https://example.com"}) is False


def test_show_no_blocks_tool() -> None:
    cfg = _make_config(enabled=True, high_risk_only=True)
    c = _make_collector(cfg, ["3"])
    decision = _run(c.show("exec", {"command": "rm -rf /"}))
    assert decision.choice is PermissionChoice.NO
    # Negative answer does NOT add to the allow-list.
    assert c.needs_prompt("exec", {"command": "rm -rf /"}) is True


def test_show_esc_cancels() -> None:
    cfg = _make_config(enabled=True, high_risk_only=True)
    c = _make_collector(cfg, ["esc"])
    decision = _run(c.show("exec", {"command": "rm -rf /"}))
    assert decision.choice is PermissionChoice.CANCEL


def test_show_keyboard_interrupt_is_cancel() -> None:
    cfg = _make_config(enabled=True, high_risk_only=True)

    def raise_interrupt(_prompt: str) -> str:
        raise KeyboardInterrupt

    c = PermissionCollector(cfg, input_fn=raise_interrupt)
    decision = _run(c.show("exec", {"command": "rm -rf /"}))
    assert decision.choice is PermissionChoice.CANCEL


def test_show_default_enter_is_yes() -> None:
    """Pressing Enter on its own confirms the default (Yes)."""
    cfg = _make_config(enabled=True, high_risk_only=True)
    c = _make_collector(cfg, [""])
    decision = _run(c.show("exec", {"command": "ls"}))
    assert decision.choice is PermissionChoice.YES


def test_show_unknown_input_defaults_to_yes() -> None:
    cfg = _make_config(enabled=True, high_risk_only=True)
    c = _make_collector(cfg, ["???"])
    decision = _run(c.show("exec", {"command": "ls"}))
    assert decision.choice is PermissionChoice.YES


# ---------------------------------------------------------------------------
# Body rendering
# ---------------------------------------------------------------------------


def test_prompt_body_includes_tool_name_and_args() -> None:
    cfg = _make_config(enabled=True, high_risk_only=True)
    captured: list[str] = []
    c = _make_collector(cfg, ["1"], captured)
    _run(c.show("exec", {"command": "rm -rf /tmp/foo"}))
    body = captured[0]
    assert "Exec" in body  # humanized
    assert "rm -rf /tmp/foo" in body or "rm -rf" in body
    assert "Yes" in body
    assert "No" in body


def test_prompt_body_marks_out_of_scope_path() -> None:
    cfg = _make_config(enabled=True, high_risk_only=True)
    captured: list[str] = []
    # workspace = ~/femtobot; a path under /tmp/evil.py is out of scope
    # (write_file gets promoted to HIGH).
    c = _make_collector(cfg, ["1"], captured)
    _run(c.show("write_file", {"path": "/tmp/evil.py"}))
    body = captured[0]
    assert "Write File" in body
    assert "OUTSIDE" in body or "outside" in body


# ---------------------------------------------------------------------------
# Session reset
# ---------------------------------------------------------------------------


def test_reset_clears_allow_list() -> None:
    cfg = _make_config(enabled=True, high_risk_only=True)
    c = _make_collector(cfg, ["2"])
    _run(c.show("exec", {"command": "ls"}))
    # Allowed for the session.
    assert c.needs_prompt("exec", {"command": "ls"}) is False
    c.reset()
    # Reset wipes the allow list — next call must prompt again.
    assert c.needs_prompt("exec", {"command": "ls"}) is True


# ---------------------------------------------------------------------------
# Decision dataclass
# ---------------------------------------------------------------------------


def test_decision_carries_assessment() -> None:
    cfg = _make_config(enabled=True, high_risk_only=True)
    c = _make_collector(cfg, ["1"])
    decision = _run(c.show("exec", {"command": "ls"}))
    assert isinstance(decision, PermissionDecision)
    assert decision.assessment.level.value == "high"
