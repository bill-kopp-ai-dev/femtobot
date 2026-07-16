"""Verify Femtobot cannot self-replicate via the ``exec`` tool.

longlogs.txt 2026-07-15 15:53: a ``.femtobot_ok/`` instance was created
on disk while the operator was away — most likely via ``femtobot
onboard --suffix ok`` invoked through the agent's ``exec`` tool. Block
that at the command-safety layer so the agent cannot bootstrap siblings.
"""
import pytest

from femtobot.security.command_guard import check_command_safety


def test_femtobot_onboard_blocked():
    ok, reason = check_command_safety(
        "femtobot onboard --suffix ok",
        workspace_root=None,
    )
    assert ok is False, "femtobot onboard must be blocked"
    assert "deny pattern" in reason.lower() or "blocked" in reason.lower()


def test_femtobot_init_blocked():
    ok, reason = check_command_safety(
        "femtobot init --suffix dev",
        workspace_root=None,
    )
    assert ok is False


def test_femtobot_new_blocked():
    ok, reason = check_command_safety(
        "femtobot new my-instance",
        workspace_root=None,
    )
    assert ok is False


def test_ls_still_allowed():
    """Sanity: ordinary inspection commands must still pass."""
    ok, _ = check_command_safety(
        "ls -la .femtobot_ok/",
        workspace_root=None,
    )
    assert ok is True, "ls must remain allowed"


def test_user_can_override_with_allow_patterns():
    """Operators who really want this can opt in via allow_patterns."""
    ok, _ = check_command_safety(
        "femtobot onboard --suffix ok",
        workspace_root=None,
        allow_patterns=[r"femtobot\s+onboard"],
    )
    assert ok is True, "explicit allow_patterns must override deny"