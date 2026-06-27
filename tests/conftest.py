"""Pytest fixtures for femtobot tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def workspace_path(tmp_path: Path) -> Path:
    """A scratch workspace path used by skills / MCP tests."""
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return ws


@pytest.fixture
def instance_dir(tmp_path: Path) -> Path:
    """A scratch instance directory mimicking ``.femtobot``."""
    inst = tmp_path / ".femtobot_test"
    inst.mkdir(parents=True, exist_ok=True)
    (inst / "workspace").mkdir(parents=True, exist_ok=True)
    (inst / "workspace" / "memory").mkdir(parents=True, exist_ok=True)
    return inst
