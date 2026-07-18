"""Regression tests for the 2026-07-18 bug-audit fixes.

Each test exercises one of the bugs reported in
``femtobot-bugs-found.md`` and confirms the fix is in place.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from femtobot.agent.toolsets.femtobot_timer import _impl as femtobot_timer_impl
from femtobot.agent.deps import FemtobotDeps
from femtobot.config.schema import Config
from femtobot.security.command_guard import check_command_safety
from femtobot.security.workspace_access import current_scope_allows_loopback


# ---------------------------------------------------------------------------
# Bug 1 (CRITICAL): command_guard hardcoded enabled=False
# ---------------------------------------------------------------------------


def test_command_safety_loopback_kwarg_exists() -> None:
    """loopback_enabled must be a parameter of check_command_safety."""
    import inspect

    sig = inspect.signature(check_command_safety)
    assert "loopback_enabled" in sig.parameters, (
        "check_command_safety must accept loopback_enabled kwarg "
        "(audit 2026-07-18 bug #1)"
    )


def test_command_safety_loopback_default_is_true() -> None:
    """Default loopback_enabled=True preserves historical behavior."""
    import inspect

    sig = inspect.signature(check_command_safety)
    assert sig.parameters["loopback_enabled"].default is True


def test_command_safety_blocks_loopback_when_disabled(monkeypatch) -> None:
    """When loopback_enabled=False, a command targeting 127.0.0.1 is blocked."""
    # Force current_scope_allows_loopback to return False (no WebUI Full Access).
    monkeypatch.setattr(
        "femtobot.security.command_guard.current_scope_allows_loopback",
        lambda *, enabled: enabled and True,  # honor the enabled flag
    )
    ok, reason = check_command_safety(
        "curl http://127.0.0.1:8080/health",
        workspace_root=None,
        restrict_to_workspace=False,
        loopback_enabled=False,
    )
    assert not ok
    assert "internal" in reason.lower() or "private" in reason.lower()


def test_command_safety_allows_loopback_when_enabled(monkeypatch) -> None:
    """When loopback_enabled=True, the same command passes the loopback check."""
    # Force the scope check to honor the enabled flag.
    monkeypatch.setattr(
        "femtobot.security.command_guard.current_scope_allows_loopback",
        lambda *, enabled: bool(enabled),
    )
    ok, reason = check_command_safety(
        "curl http://127.0.0.1:8080/health",
        workspace_root=None,
        restrict_to_workspace=False,
        loopback_enabled=True,
    )
    assert ok, f"curl loopback should be allowed when enabled=True; got {reason!r}"


# ---------------------------------------------------------------------------
# Bug 2 (HIGH): websocket _is_localhost stub returns True always
# ---------------------------------------------------------------------------


def test_is_localhost_rejects_remote_address() -> None:
    from femtobot.channels.websocket import _is_localhost

    # A connection from a public IP must NOT be treated as localhost.
    remote = MagicMock()
    remote.remote_address = ("203.0.113.42", 54321)
    assert _is_localhost(remote) is False


def test_is_localhost_accepts_ipv4_loopback() -> None:
    from femtobot.channels.websocket import _is_localhost

    conn = MagicMock()
    conn.remote_address = ("127.0.0.1", 12345)
    assert _is_localhost(conn) is True


def test_is_localhost_accepts_ipv4_loopback_subnet() -> None:
    from femtobot.channels.websocket import _is_localhost

    conn = MagicMock()
    conn.remote_address = ("127.0.0.5", 12345)
    assert _is_localhost(conn) is True


def test_is_localhost_accepts_ipv6_loopback() -> None:
    from femtobot.channels.websocket import _is_localhost

    conn = MagicMock()
    conn.remote_address = ("::1", 12345, 0, 0)
    assert _is_localhost(conn) is True


def test_is_localhost_accepts_ipv4_mapped_ipv6() -> None:
    from femtobot.channels.websocket import _is_localhost

    conn = MagicMock()
    conn.remote_address = ("::ffff:127.0.0.1", 12345, 0, 0)
    assert _is_localhost(conn) is True


def test_is_localhost_rejects_none() -> None:
    from femtobot.channels.websocket import _is_localhost

    assert _is_localhost(None) is False


def test_is_localhost_rejects_missing_address() -> None:
    from femtobot.channels.websocket import _is_localhost

    conn = MagicMock(spec=[])  # no remote_address attr
    assert _is_localhost(conn) is False


# ---------------------------------------------------------------------------
# Bug 7 (MEDIUM): femtobot_timer DST detection
# ---------------------------------------------------------------------------


def test_femtobot_timer_dst_detection_uses_active_flag() -> None:
    """The calendar output's 'DST active' line must reflect current DST state,
    not just whether the zone has DST rules."""
    cfg = Config()
    cfg.agents.defaults.timezone = "UTC"  # UTC has no DST
    deps = FemtobotDeps(config=cfg, workspace=MagicMock())
    result = femtobot_timer_impl("calendar", deps)
    # UTC's dst() returns timedelta(0), so the new logic reports False.
    assert "DST active: False" in result


def test_femtobot_timer_dst_flag_var_name_resolved() -> None:
    """Regression: the f-string used 'dst' but only 'dst_active' was defined."""
    cfg = Config()
    cfg.agents.defaults.timezone = "UTC"
    deps = FemtobotDeps(config=cfg, workspace=MagicMock())
    # Must not raise NameError on 'dst'.
    femtobot_timer_impl("calendar", deps)


# ---------------------------------------------------------------------------
# Bug 6 (MEDIUM): shell timeout=0 should disable limit, not fall through
# ---------------------------------------------------------------------------


def test_shell_resolve_timeout_zero_means_no_limit() -> None:
    """_resolve_timeout(0) must return 0 (the cap), preserving the
    '0 disables the limit' contract documented at #3595."""
    from femtobot.agent.tools.shell import ExecTool

    # Build a minimal ExecTool with self.timeout=None so the only way
    # to set a limit is via the argument.
    shell = ExecTool(timeout=None)
    assert shell._resolve_timeout(0) == 0
    # Sanity: explicit None still defers to config (None here).
    assert shell._resolve_timeout(None) is None
    # Sanity: a real timeout is capped at SHELL_MAX_TIMEOUT_S.
    from femtobot.agent.tools.shell import SHELL_MAX_TIMEOUT_S

    assert shell._resolve_timeout(SHELL_MAX_TIMEOUT_S + 999) == SHELL_MAX_TIMEOUT_S


# ---------------------------------------------------------------------------
# Bug 4 (HIGH): loop.py suppress(Exception) engulfs real bugs
# ---------------------------------------------------------------------------


def test_loop_module_no_broad_suppress_in_cancel_path() -> None:
    """_cancel_active_tasks must not have a bare ``suppress(... Exception)``.

    The grep-based test inlines the relevant fragment to avoid coupling
    to test internals of AgentLoop.
    """
    import inspect

    from femtobot.agent.loop import AgentLoop

    src = inspect.getsource(AgentLoop._cancel_active_tasks)
    # Either the broad ``Exception`` was removed entirely, or the
    # suppression logs via logger.exception — never silent.
    if "suppress(" in src and "Exception" in src:
        # If suppress is still used, it must only catch CancelledError.
        # (The current fix removes it altogether and logs instead.)
        pytest.fail(
            "_cancel_active_tasks still uses suppress(... Exception); "
            "this swallows real bugs during cancellation cleanup."
        )


# ---------------------------------------------------------------------------
# Bug 5 (MEDIUM): autocompact TOCTOU on _archiving set
# ---------------------------------------------------------------------------


def test_autocompact_check_expired_uses_atomic_add() -> None:
    """The TOCTOU pair `if key in self._archiving: ... self._archiving.add(key)`
    must be collapsed into a single ``add`` call (set.add returns True only
    when the element was newly inserted)."""
    import inspect

    from femtobot.agent.autocompact import AutoCompact

    src = inspect.getsource(AutoCompact.check_expired)
    # The atomic guard ``self._archiving.add(key)`` must be present.
    assert "self._archiving.add(key)" in src, (
        "check_expired must use self._archiving.add(key) as the atomic guard"
    )
    # The buggy ``if ... key in self._archiving: continue`` form must be gone
    # from the function body. A comment mentioning the old form is OK.
    body = "\n".join(
        line for line in src.splitlines() if not line.strip().startswith("#")
    )
    assert "key in self._archiving" not in body, (
        "check_expired still has a TOCTOU check on self._archiving"
    )
