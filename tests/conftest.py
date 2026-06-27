"""Pytest fixtures for femtobot tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from femtobot.config.loader import clear_instance_dir


@pytest.fixture(autouse=True)
def _isolate_femtobot_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scrub any FEMTOBOT_* env vars that might leak from the developer's shell.

    Without this, ``Config()`` (a Pydantic ``BaseSettings``) would silently
    absorb real provider API keys from the shell and tests like
    ``test_write_default_config_no_warning_when_clean`` would suddenly fail
    the moment the user adds a real ``.env`` next to the project. Applied to
    every test (autouse) and clears the loader's cached instance dir between
    runs.
    """
    for var in list(os.environ):
        if var.startswith("FEMTOBOT_"):
            monkeypatch.delenv(var, raising=False)
    clear_instance_dir()
    yield
    clear_instance_dir()


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
