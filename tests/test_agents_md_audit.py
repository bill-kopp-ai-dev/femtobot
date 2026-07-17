"""Tests for the AGENTS.md / SOUL.md auditor (PR 5.1)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from femtobot.scripts.audit_agents_md import (
    audit_text,
    audit_workspace,
    find_contradictions,
)

pytestmark = pytest.mark.audit


def test_audit_text_detects_autonomous_section():
    findings = audit_text(
        "AGENTS.md",
        "## Agent Loop Discipline\nIf a task needs a tool, "
        "emit the tool call in the same turn. Never end a turn with "
        "only 'vou fazer'.\n",
    )
    assert any(f.posture == "autonomous" for f in findings)


def test_audit_text_detects_ask_first_section():
    findings = audit_text(
        "SOUL.md",
        "## Default Posture\nBefore taking action, ask the user "
        "for approval.\n",
    )
    assert any(f.posture == "ask_first" for f in findings)


def test_find_contradictions_flags_both_postures_in_same_workspace(tmp_path):
    agents = tmp_path / "AGENTS.md"
    agents.write_text(
        "## Agent Loop Discipline\n"
        "If a task needs a tool, emit the tool call in the same turn.\n",
        encoding="utf-8",
    )
    soul = tmp_path / "SOUL.md"
    soul.write_text(
        "## Default Posture\nBefore proceeding, ask the user.\n",
        encoding="utf-8",
    )
    report = audit_workspace(tmp_path)
    kinds = [c["kind"] for c in report["contradictions"]]
    assert "autonomous_vs_ask_first" in kinds


def test_find_contradictions_clean_when_only_autonomous(tmp_path):
    (tmp_path / "AGENTS.md").write_text(
        "## Loop\nNever end a turn with only 'vou fazer'.\n",
        encoding="utf-8",
    )
    report = audit_workspace(tmp_path)
    assert report["contradictions"] == []


def test_audit_text_handles_empty_sections():
    assert audit_text("X.md", "") == []
    assert audit_text("X.md", "## \n\n## Other\nbody") == []


def test_cli_json_emits_valid_json(tmp_path):
    (tmp_path / "AGENTS.md").write_text(
        "## Loop\nBe autonomous.\n"
        "## Posture\nBefore proceeding, ask the user.\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, "-m", "femtobot.scripts.audit_agents_md",
         str(tmp_path), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)
    assert data["workspace"] == str(tmp_path)
    assert data["files_scanned"] == ["AGENTS.md"]
    assert any(c["kind"] == "autonomous_vs_ask_first" for c in data["contradictions"])
