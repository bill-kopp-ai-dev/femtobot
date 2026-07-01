"""Tests for the bash-mode module."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from femtobot.cli.bash_mode import (
    DEFAULT_TIMEOUT_S,
    BashRunResult,
    extract_command,
    format_bash_output,
    is_repeat_request,
    looks_like_bash_mode,
    parse_timeout,
    run_bash_command,
)


def test_looks_like_bash_mode() -> None:
    assert looks_like_bash_mode("!ls") is True
    assert looks_like_bash_mode("  !pwd") is True
    assert looks_like_bash_mode("ls") is False
    assert looks_like_bash_mode("") is False


def test_extract_command_strips_bang() -> None:
    assert extract_command("!ls -la") == "ls -la"
    assert extract_command("  ! echo hi") == "echo hi"
    assert extract_command("! ") == ""
    assert extract_command("!ls") == "ls"


def test_is_repeat_request() -> None:
    assert is_repeat_request("!!") is True
    assert is_repeat_request("! !") is True
    assert is_repeat_request("!ls") is False


def test_parse_timeout_default() -> None:
    assert parse_timeout(None) == DEFAULT_TIMEOUT_S


def test_parse_timeout_from_config() -> None:
    cfg = SimpleNamespace(
        agents=SimpleNamespace(
            defaults=SimpleNamespace(cli=SimpleNamespace(bash_mode_timeout_s=12.5))
        )
    )
    assert parse_timeout(cfg) == 12.5


def test_parse_timeout_clamps_minimum() -> None:
    cfg = SimpleNamespace(
        agents=SimpleNamespace(
            defaults=SimpleNamespace(cli=SimpleNamespace(bash_mode_timeout_s=0.1))
        )
    )
    assert parse_timeout(cfg) >= 1.0


def test_run_bash_command_success() -> None:
    result = asyncio.run(run_bash_command("echo hello", timeout_s=5.0))
    assert result.exit_code == 0
    assert "hello" in result.stdout
    assert result.timed_out is False


def test_run_bash_command_nonzero_exit() -> None:
    result = asyncio.run(run_bash_command("false", timeout_s=5.0))
    assert result.exit_code != 0
    assert result.timed_out is False


def test_run_bash_command_timeout() -> None:
    """A 30s sleep with a 0.1s timeout must report timed_out=True."""
    result = asyncio.run(run_bash_command("sleep 30", timeout_s=0.1))
    assert result.timed_out is True


def test_run_bash_command_empty() -> None:
    result = asyncio.run(run_bash_command(""))
    assert result.empty is True


def test_format_bash_output_success() -> None:
    r = BashRunResult("echo hi", 0, "hi\n", "", 0.1, False, False)
    s = format_bash_output(r)
    assert "$ echo hi" in s
    assert "hi" in s
    assert "[exit" not in s


def test_format_bash_output_with_stderr() -> None:
    r = BashRunResult("cmd", 2, "out", "warn", 0.1, False, False)
    s = format_bash_output(r)
    assert "[stderr]" in s
    assert "warn" in s
    assert "[exit 2]" in s


def test_format_bash_output_timed_out() -> None:
    r = BashRunResult("slow", -1, "", "", 5.0, True, False)
    s = format_bash_output(r)
    assert "$ slow" in s
    assert "timed out" in s
