"""Tests for ``femtobot doctor`` (PR 7.2)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from femtobot.cli.doctor import render_report, run_doctor


def _run_sync(fn):
    """Run a coroutine without leaking event loops across tests."""
    import asyncio

    return asyncio.new_event_loop().run_until_complete(fn)


def test_run_doctor_clean_workspace(tmp_path):
    report = run_doctor(workspace=tmp_path)
    assert report["overall"] in {"OK", "WARN"}  # live_race is WARN on TTY
    assert "config" in report["checks"]
    assert "mcp_servers" in report["checks"]
    assert "spinner" in report["checks"]
    assert "live_race" in report["checks"]


def test_run_doctor_detects_unreferenced_mcp(tmp_path):
    agents = tmp_path / "AGENTS.md"
    agents.write_text(
        "# Workspace\n"
        "Use `mcp_percival-osm_geocode` to resolve addresses.\n",
        encoding="utf-8",
    )
    # Pass an explicit empty config so the check does not see the real
    # ``.femtobot/config.json`` (which has ``percival-osm`` configured) and
    # incorrectly report OK. This is the seam that lets the test stay
    # deterministic regardless of the developer's local instance state.
    empty_config = SimpleNamespace(tools=SimpleNamespace(mcp_servers={}))
    report = run_doctor(workspace=tmp_path, config=empty_config)
    mcp = report["checks"]["mcp_servers"]
    assert mcp["status"] == "WARN"
    assert "percival-osm" in mcp["detail"]


def test_run_doctor_no_workspace_does_not_crash():
    report = run_doctor(workspace=None)
    assert "checks" in report
    assert report["checks"]["mcp_servers"]["status"] == "OK"


def test_render_report_is_markdown_table():
    report = run_doctor(workspace=None)
    text = render_report(report)
    assert "# femtobot doctor" in text
    assert "Overall:" in text
    assert "| Check | Status | Detail |" in text
