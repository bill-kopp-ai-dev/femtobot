"""Tests for the md_commands module (Camada 2, T2.2)."""

from __future__ import annotations

import subprocess

from femtobot.cli.md_commands import (
    parse_skill,
    render_skill,
    skill_to_command_spec,
    SkillSpec,
)


def test_parse_frontmatter() -> None:
    # YAML interprets unquoted [...] as a list.
    raw = """---
name: /review
description: Review a PR
argument_hint: pr-url
tags:
  - code-review
  - security
bypass_llm: false
---
Body content here."""
    spec = parse_skill(raw)
    assert spec.name == "/review"
    assert spec.description == "Review a PR"
    assert spec.argument_hint == "pr-url"
    assert spec.tags == ("code-review", "security")
    assert spec.bypass_llm is False
    assert "Body content" in spec.body


def test_parse_no_frontmatter() -> None:
    raw = "Just a plain body without YAML."
    spec = parse_skill(raw)
    assert spec.name == ""
    assert spec.body == raw


def test_parse_body_with_frontmatter_separator() -> None:
    raw = "---\nname: /cmd\n---\nReal body."
    spec = parse_skill(raw)
    assert spec.name == "/cmd"
    assert spec.body == "Real body."


def test_render_substitutes_arguments() -> None:
    spec = SkillSpec(name="/test", description="", body="Args: $ARGUMENTS | 1: $1 | 2: $2")
    result = render_skill(spec, "foo bar baz")
    assert "foo bar baz" in result
    assert "foo" in result  # $1
    assert "bar" in result  # $2


def test_render_unknown_var_becomes_empty() -> None:
    """Unknown $VAR → Jinja2 → renders as empty string (no exception)."""
    spec = SkillSpec(name="/t", body="Hello $UNKNOWN_VAR and $1")
    result = render_skill(spec, "pos1 pos2")
    # Unknown $UNKNOWN_VAR → empty; $1 → "pos1"
    assert "pos1" in result
    assert "UNKNOWN_VAR" not in result
    assert "$UNKNOWN_VAR" not in result


def test_skill_to_command_spec() -> None:
    spec = SkillSpec(name="/review", description="Review PR", bypass_llm=False)
    cmd = skill_to_command_spec(spec)
    assert cmd.command == "/review"
    assert cmd.description == "Review PR"
    assert cmd.icon == "file-code"  # bypass_llm=False → file-code


def test_skill_to_command_spec_bypass_llm() -> None:
    spec = SkillSpec(name="/bypass", description="x", bypass_llm=True)
    cmd = skill_to_command_spec(spec)
    assert cmd.icon == "book-open"  # bypass_llm=True → book-open


# ---------------------------------------------------------------------------
# Bash inline substitution (Camada 2, T2 - Hardening)
# ---------------------------------------------------------------------------

import pytest

from femtobot.cli.md_commands import _run_bash_inlines


def _fake_run_success(cmd: str | list, **kwargs: object) -> subprocess.CompletedProcess[str]:
    """Fake subprocess.run that always returns stdout='OK'."""
    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="OK\n", stderr="")


def _fake_run_failure(cmd: str | list, **kwargs: object) -> subprocess.CompletedProcess[str]:
    """Fake subprocess.run that simulates a failed command."""
    return subprocess.CompletedProcess(args=cmd, returncode=127, stdout="", stderr="command not found")


def _fake_run_stderr_only(cmd: str | list, **kwargs: object) -> subprocess.CompletedProcess[str]:
    """Fake subprocess.run that only has stderr output."""
    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="warning only\n")


def _fake_run_timeout(cmd: str | list, **kwargs: object) -> subprocess.CompletedProcess[str]:
    """Fake subprocess.run that raises TimeoutExpired."""
    raise subprocess.TimeoutExpired(cmd=cmd if isinstance(cmd, str) else " ".join(cmd), timeout=0.001)


def test_m1_bash_inline_valid_command_substituted(monkeypatch: pytest.MonkeyPatch) -> None:
    """M1: !`echo hello` → stdout 'OK' substituted."""
    monkeypatch.setattr(subprocess, "run", _fake_run_success)
    result = _run_bash_inlines("Result: !`echo hello`")
    assert "Result: OK" in result


def test_m2_bash_inline_failure_returns_empty_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """M2: failed command (non-zero exit) → returns empty string, no crash."""
    monkeypatch.setattr(subprocess, "run", _fake_run_failure)
    result = _run_bash_inlines("Output: !`badcmd`")
    assert result == "Output: "  # stdout empty, no crash


def test_m3_bash_inline_timeout_no_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """M3: timeout → error string without crashing."""
    monkeypatch.setattr(subprocess, "run", _fake_run_timeout)
    result = _run_bash_inlines("Value: !`sleep 999`")
    assert "[bash error:" in result


def test_m4_bash_inline_stderr_only_empty_substitution(monkeypatch: pytest.MonkeyPatch) -> None:
    """M4: command with stderr-only output → empty string substitution."""
    monkeypatch.setattr(subprocess, "run", _fake_run_stderr_only)
    result = _run_bash_inlines("X:!`warncmd` Y")
    assert "X: Y" in result  # substitution is empty (only stderr, no stdout)


def test_m5_bash_inline_multiple_commands_all_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    """M5: multiple !`cmd` → all resolved with output."""
    monkeypatch.setattr(subprocess, "run", _fake_run_success)
    result = _run_bash_inlines("A:!`cmd1` B:!`cmd2` C:!`cmd3`")
    assert result.count("OK") == 3


def test_m6_security_no_bash_pattern_no_subprocess_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """M6: no !`cmd` pattern → subprocess.run never called."""
    run_calls: list[object] = []

    def track_run(cmd: str | list, **kwargs: object) -> subprocess.CompletedProcess[str]:
        run_calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="OK\n", stderr="")

    monkeypatch.setattr(subprocess, "run", track_run)
    spec = SkillSpec(name="/plain", body="Plain text, no bash here")
    result = render_skill(spec, "", unsafe_bypass=True)
    assert run_calls == []
    assert "OK" not in result


def test_m7_plain_jinja2_render_with_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """M7: plain skill renders via Jinja2 with argument substitution."""
    run_calls: list[object] = []

    def track_run(cmd: str | list, **kwargs: object) -> subprocess.CompletedProcess[str]:
        run_calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="OK\n", stderr="")

    monkeypatch.setattr(subprocess, "run", track_run)
    spec = SkillSpec(name="/greet", body="Hello $1")
    result = render_skill(spec, "World", unsafe_bypass=True)
    assert "World" in result
    assert run_calls == []  # no bash inlines, so subprocess not called
