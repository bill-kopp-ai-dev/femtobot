"""Regression tests for the v0.1.3 E2E cwd-anchor bug.

The E2E regression prompt ``tests/E2E_REGRESSION_PROMPT.md`` showed that
``exec`` and ``read_file``/``find_files`` were anchoring their default
``cwd`` / relative-path resolution on ``.femtobot/workspace`` (the
Femtobot internal notes directory), so commands like ``ls femtobot/agent``
silently missed the user's source tree.

These tests pin the fix in :mod:`femtobot.agent.tools.path_utils`,
:mod:`femtobot.agent.tools.shell` and :mod:`femtobot.agent.tools.filesystem`.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from femtobot.config import loader as femtobot_loader
from femtobot.agent.tools.path_utils import (
    get_project_root,
    resolve_default_cwd,
)


# ---------------------------------------------------------------------------
# path_utils helpers
# ---------------------------------------------------------------------------


def _force_instance_dir(instance_dir: Path) -> None:
    """Override ``get_instance_dir`` to a deterministic test directory."""
    femtobot_loader._current_instance_dir = instance_dir


def test_get_project_root_returns_parent_of_instance_dir(tmp_path: Path) -> None:
    """The project root is the parent of ``.femtobot``."""
    instance = tmp_path / ".femtobot"
    instance.mkdir()
    workspace = instance / "workspace"
    workspace.mkdir()
    _force_instance_dir(instance)
    try:
        assert get_project_root() == tmp_path
    finally:
        femtobot_loader._current_instance_dir = None


def test_resolve_default_cwd_uses_project_root_when_unrestricted(tmp_path: Path) -> None:
    """``resolve_default_cwd`` falls back to the project root when the agent
    is not restricted to its workspace."""
    instance = tmp_path / ".femtobot"
    instance.mkdir()
    workspace = instance / "workspace"
    workspace.mkdir()
    _force_instance_dir(instance)
    try:
        assert resolve_default_cwd(workspace=workspace, restrict_to_workspace=False) == tmp_path
        assert resolve_default_cwd(workspace=None, restrict_to_workspace=False) == tmp_path
    finally:
        femtobot_loader._current_instance_dir = None


def test_resolve_default_cwd_keeps_workspace_when_restricted(tmp_path: Path) -> None:
    """``resolve_default_cwd`` keeps the workspace when sandboxing is on."""
    instance = tmp_path / ".femtobot"
    instance.mkdir()
    workspace = instance / "workspace"
    workspace.mkdir()
    _force_instance_dir(instance)
    try:
        assert resolve_default_cwd(workspace=workspace, restrict_to_workspace=True) == workspace
    finally:
        femtobot_loader._current_instance_dir = None


def test_resolve_default_cwd_falls_back_to_workspace_when_no_project_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the project root cannot be discovered, fall back to workspace."""
    from femtobot.agent.tools import path_utils as path_utils_mod

    # Pretend the instance_dir has no parent (degenerate case).
    fake_instance = Path("/")
    monkeypatch.setattr(
        path_utils_mod,
        "get_instance_dir",
        lambda: fake_instance,
    )
    workspace = Path("/var/somewhere")
    result = resolve_default_cwd(workspace=workspace, restrict_to_workspace=False)
    # ``Path("/").parent == Path("/")`` → get_project_root returns None → fall back.
    assert result == workspace


# ---------------------------------------------------------------------------
# shell.ExecTool — _prepare_command default cwd
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exec_default_cwd_is_project_root_when_unrestricted(tmp_path: Path) -> None:
    """``exec`` runs in the project root, not the Femtobot workspace, when
    ``restrict_to_workspace`` is False."""
    from femtobot.agent.tools.shell import ExecTool

    instance = tmp_path / ".femtobot"
    instance.mkdir()
    workspace = instance / "workspace"
    workspace.mkdir()
    _force_instance_dir(instance)

    try:
        tool = ExecTool(
            working_dir=str(workspace),
            restrict_to_workspace=False,
        )
        prepared = tool._prepare_command("ls femtobot/agent")
        # If ``_prepare_command`` returned an error string, fail loudly.
        assert not isinstance(prepared, str), prepared
        assert prepared.cwd == str(tmp_path), (
            f"expected cwd={tmp_path}, got {prepared.cwd}"
        )
    finally:
        femtobot_loader._current_instance_dir = None


@pytest.mark.asyncio
async def test_exec_default_cwd_is_workspace_when_restricted(tmp_path: Path) -> None:
    """``exec`` keeps the workspace as cwd when sandboxing is enforced."""
    from femtobot.agent.tools.shell import ExecTool

    instance = tmp_path / ".femtobot"
    instance.mkdir()
    workspace = instance / "workspace"
    workspace.mkdir()
    _force_instance_dir(instance)

    try:
        tool = ExecTool(
            working_dir=str(workspace),
            restrict_to_workspace=True,
        )
        prepared = tool._prepare_command("ls")
        assert not isinstance(prepared, str), prepared
        assert prepared.cwd == str(workspace)
    finally:
        femtobot_loader._current_instance_dir = None


@pytest.mark.asyncio
async def test_exec_explicit_working_dir_overrides_default(tmp_path: Path) -> None:
    """When the LLM passes ``working_dir=``, it always wins."""
    from femtobot.agent.tools.shell import ExecTool

    instance = tmp_path / ".femtobot"
    instance.mkdir()
    workspace = instance / "workspace"
    workspace.mkdir()
    _force_instance_dir(instance)

    try:
        tool = ExecTool(
            working_dir=str(workspace),
            restrict_to_workspace=False,
        )
        custom = tmp_path / "elsewhere"
        custom.mkdir()
        prepared = tool._prepare_command("pwd", working_dir=str(custom))
        assert not isinstance(prepared, str), prepared
        assert prepared.cwd == str(custom.resolve())
    finally:
        femtobot_loader._current_instance_dir = None


# ---------------------------------------------------------------------------
# filesystem._FsTool — _resolve default anchor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_file_relative_path_uses_project_root(tmp_path: Path) -> None:
    """``read_file femtobot/agent/runner.py`` resolves under the project
    root, not under ``.femtobot/workspace``."""
    from femtobot.agent.tools.filesystem import ReadFileTool

    instance = tmp_path / ".femtobot"
    instance.mkdir()
    workspace = instance / "workspace"
    workspace.mkdir()
    # Create a real source file under the project root.
    src_dir = tmp_path / "femtobot" / "agent"
    src_dir.mkdir(parents=True)
    target = src_dir / "runner.py"
    target.write_text("print('hello')\n")

    _force_instance_dir(instance)

    try:
        tool = ReadFileTool(workspace=workspace, restrict_to_workspace=False)
        resolved = tool._resolve("femtobot/agent/runner.py")
        assert resolved == target.resolve(), (
            f"expected {target.resolve()}, got {resolved}"
        )
    finally:
        femtobot_loader._current_instance_dir = None


@pytest.mark.asyncio
async def test_read_file_relative_path_still_restricted_when_restricted(
    tmp_path: Path,
) -> None:
    """When ``restrict_to_workspace`` is True, relative paths still anchor
    on the workspace (no behaviour change for sandboxed installs)."""
    from femtobot.agent.tools.filesystem import ReadFileTool

    instance = tmp_path / ".femtobot"
    instance.mkdir()
    workspace = instance / "workspace"
    workspace.mkdir()

    _force_instance_dir(instance)

    try:
        tool = ReadFileTool(workspace=workspace, restrict_to_workspace=True)
        # Create a file inside the workspace.
        target = workspace / "AGENTS.md"
        target.write_text("# Agents\n")
        resolved = tool._resolve("AGENTS.md")
        # Should anchor on the workspace, not the project root.
        assert str(resolved).startswith(str(workspace.resolve()))
    finally:
        femtobot_loader._current_instance_dir = None
