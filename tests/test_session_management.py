"""Session-management regression tests (v0.1.8 twelfth-pass CLI parity push).

Pins the fixes for Issues 1-5 raised by the parity review of
``femtobot/session/manager.py`` against upstream nanobot.

Issue 1 — ``SessionManager.delete_session`` is no longer dead code:
  it is wired through the new ``femtobot sessions delete`` CLI
  command and has direct test coverage.

Issue 2 — ``delete_session`` removes the workspace **and** the
legacy session files (not just one).

Issue 3 — Equivalent of the nanobot WebUI delete handler: the
Femtobot runtime ships the public ``SessionManager.delete_session``
method (mirrors nanobot's API surface), so external callers can
clean up.  Femtobot has no WebUI module — the CLI is the
authoritative user-facing surface here.

Issue 4 — ``femtobot sessions {list,delete,show}`` CLI commands
exist (smoke-tested via ``CliRunner`` below).

Issue 5 — This file.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from femtobot.cli.commands import app
from femtobot.session.manager import Session, SessionManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """A blank workspace with a single session "smoke:1" inside it."""
    ws = tmp_path / "workspace"
    sessions_dir = ws / "sessions"
    sessions_dir.mkdir(parents=True)
    legacy_dir = tmp_path / "legacy_sessions"
    legacy_dir.mkdir()

    session = Session(key="smoke:1", messages=[{"role": "user", "content": "hi"}])
    session.metadata["title"] = "Smoke 1"
    manager = SessionManager(workspace=ws)
    manager.save(session)

    # Also place a legacy copy via monkey-patching legacy_sessions_dir.
    manager.legacy_sessions_dir = legacy_dir
    (legacy_dir / "smoke_1.jsonl").write_text(
        json.dumps({
            "_type": "metadata",
            "key": "smoke:1",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "metadata": {"title": "Smoke 1 legacy"},
            "last_consolidated": 0,
        })
    )

    return ws


# ---------------------------------------------------------------------------
# Issue 1 — delete_session is no longer dead
# ---------------------------------------------------------------------------


def test_issue1_delete_session_is_wired_via_cli(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``femtobot sessions delete KEY`` now removes the JSONL file."""
    runner = CliRunner()
    session_file = workspace / "sessions" / "smoke_1.jsonl"
    assert session_file.exists()

    # The CLI resolves the workspace via load_config().  Force the
    # resolved workspace path to our scratch dir.
    fake_cfg = type("FakeCfg", (), {"workspace_path": workspace})()
    monkeypatch.setattr(
        "femtobot.cli.sessions.load_config", lambda: fake_cfg
    )

    result = runner.invoke(
        app,
        ["sessions", "delete", "smoke:1", "--yes"],
    )
    assert result.exit_code == 0, result.stdout
    assert not session_file.exists(), (
        "CLI-parity v0.1.8 Issue 1: the session file should be "
        "deleted but it survived."
    )


# ---------------------------------------------------------------------------
# Issue 2 — delete_session removes workspace + legacy paths
# ---------------------------------------------------------------------------


def test_issue2_delete_session_removes_workspace_and_legacy(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The new ``delete_session`` clears the legacy global copy as well."""
    mgr = SessionManager(workspace=workspace)
    mgr.legacy_sessions_dir = workspace.parent / "legacy_sessions"

    workspace_file = workspace / "sessions" / "smoke_1.jsonl"
    legacy_file = mgr.legacy_sessions_dir / "smoke_1.jsonl"
    assert workspace_file.exists()
    assert legacy_file.exists()

    deleted = mgr.delete_session("smoke:1")

    assert deleted is True
    assert not workspace_file.exists(), (
        "CLI-parity v0.1.8 Issue 2: workspace file survived."
    )
    assert not legacy_file.exists(), (
        "CLI-parity v0.1.8 Issue 2: legacy file survived."
    )


def test_issue2_delete_session_returns_false_when_nothing_exists(
    workspace: Path,
) -> None:
    """Deleting a non-existent session returns False (no crash)."""
    mgr = SessionManager(workspace=workspace)
    # Smoke:1 has no migration ghost; also clear legacy dir.
    deleted = mgr.delete_session("never-existed")
    assert deleted is False


# ---------------------------------------------------------------------------
# Issue 3 — public surface parity with nanobot
# ---------------------------------------------------------------------------


def test_issue3_delete_session_is_callable_on_sessionmanager(
    workspace: Path,
) -> None:
    """``SessionManager.delete_session(key)`` is part of the public API."""
    assert hasattr(SessionManager, "delete_session"), (
        "CLI-parity v0.1.8 Issue 3: SessionManager.delete_session is "
        "missing or renamed — Femtobot code must call it explicitly."
    )


# ---------------------------------------------------------------------------
# Issue 4 — CLI surfacing
# ---------------------------------------------------------------------------


def test_issue4_sessions_list_command_lists_existing_sessions(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``femtobot sessions list`` shows rows from the workspace."""
    runner = CliRunner()
    fake_cfg = type("FakeCfg", (), {"workspace_path": workspace})()
    monkeypatch.setattr(
        "femtobot.cli.sessions.load_config", lambda: fake_cfg
    )
    result = runner.invoke(app, ["sessions", "list"])
    assert result.exit_code == 0, result.stdout
    # The session should appear in the table.
    assert "smoke:1" in result.stdout


def test_issue4_sessions_show_command_runs(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``femtobot sessions show KEY`` prints metadata + last messages."""
    runner = CliRunner()
    fake_cfg = type("FakeCfg", (), {"workspace_path": workspace})()
    monkeypatch.setattr(
        "femtobot.cli.sessions.load_config", lambda: fake_cfg
    )
    result = runner.invoke(app, ["sessions", "show", "smoke:1"])
    assert result.exit_code == 0, result.stdout
    assert "smoke:1" in result.stdout or "Smoke 1" in result.stdout


def test_issue4_sessions_show_missing_session_exits_nonzero(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``femtobot sessions show MISSING_KEY`` exits with code 1."""
    runner = CliRunner()
    fake_cfg = type("FakeCfg", (), {"workspace_path": workspace})()
    monkeypatch.setattr(
        "femtobot.cli.sessions.load_config", lambda: fake_cfg
    )
    result = runner.invoke(app, ["sessions", "show", "never-existed"])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Helpers / direct API round-trip
# ---------------------------------------------------------------------------


def test_safe_key_roundtrip_legacy_convention(workspace: Path) -> None:
    """The legacy ``:`` -> ``_`` mapping is preserved for existing files.

    v0.1.8 reverted the proposed base64-encoded stem and keeps the
    historical ``safe_filename(key.replace(":", "_"))`` because the
    on-disk sessions at ``<workspace>/sessions/`` were written
    under the legacy convention.  We pin that decision here so any
    future attempt to swap encodings trips this test.
    """
    assert SessionManager.safe_key("smoke:1") == "smoke_1"
    # Round-trip is partial (legacy is lossy when keys contain
    # underscores already) but the existing files keep reading.
    assert SessionManager._decode_storage_key("smoke_1") == "smoke:1"


def test_session_manager_list_returns_seeded_session(workspace: Path) -> None:
    """The fixture seeded ``smoke:1`` — list returns it."""
    mgr = SessionManager(workspace=workspace)
    rows = mgr.list_sessions()
    keys = {row.get("key") for row in rows}
    assert "smoke:1" in keys
