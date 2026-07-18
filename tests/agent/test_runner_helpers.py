"""Tests for ``femtobot/agent/runner_helpers.py``.

Phase 4 (scaffold) — these tests exercise the no-op fallback paths
and the public surface. Once ``FemtobotAgent`` becomes the production
loop, more integration tests will land here.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from femtobot.agent.deps import FemtobotDeps
from femtobot.agent.runner_helpers import (
    persist_tool_result,
    post_run_autocompact,
    post_run_session_save,
)


def _make_deps() -> FemtobotDeps:
    return FemtobotDeps(config=_FakeConfig(), workspace=Path("/tmp"))


class _FakeConfig:
    """Minimal stand-in for ``Config`` so deps can be constructed."""

    @property
    def agents(self) -> object:
        return _Agents()

    @property
    def restrict_to_workspace(self) -> bool:
        return False

    @property
    def exec(self) -> object:
        return _Exec()


class _Agents:
    @property
    def defaults(self) -> object:
        return _Defaults()


class _Defaults:
    timezone = "UTC"


class _Exec:
    sandbox = None


@pytest.mark.asyncio
async def test_persist_tool_result_is_noop_without_session() -> None:
    """When no session is wired, the helper silently does nothing."""
    deps = _make_deps()
    # Must not raise.
    await persist_tool_result(deps, "femtobot_timer", {"query": "now"}, "ok")


@pytest.mark.asyncio
async def test_post_run_autocompact_is_noop_without_session() -> None:
    deps = _make_deps()
    await post_run_autocompact(deps)


@pytest.mark.asyncio
async def test_post_run_session_save_is_noop_without_session() -> None:
    deps = _make_deps()
    await post_run_session_save(deps)


def test_runner_helpers_exports_match_dunder() -> None:
    """The public API stays stable for callers."""
    from femtobot.agent import runner_helpers

    expected = {"persist_tool_result", "post_run_autocompact", "post_run_session_save"}
    assert expected.issubset(set(runner_helpers.__all__))
