"""``resolve_allowed_path`` containment tests (v0.0.8 third-pass B3).

Audit B3: when ``allowed_root`` is None, the previous
implementation returned the resolved path with **no containment
check at all**.  A tool that called
``resolve_allowed_path(path, allowed_root=None)`` was effectively
unrestricted — a caller could read ``/etc/passwd`` if they
bypassed the helper's caller.  We now require containment when
``restrict_to_workspace=True`` is passed (even without an explicit
``allowed_root``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from femtobot.security.workspace_policy import (
    WorkspaceBoundaryError,
    resolve_allowed_path,
)

pytestmark = pytest.mark.security


def test_explicit_allowed_root_enforced(tmp_path: Path) -> None:
    """B3: explicit ``allowed_root`` still enforces containment (B3 baseline)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    inside = ws / "ok.txt"
    inside.write_text("ok")
    # Inside the workspace: ok.
    out = resolve_allowed_path(
        str(inside),
        workspace=ws,
        allowed_root=ws,
    )
    assert out == inside.resolve()


def test_explicit_allowed_root_blocks_outside(tmp_path: Path) -> None:
    """B3: explicit ``allowed_root`` blocks outside paths (B3 baseline)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("nope")
    with pytest.raises(WorkspaceBoundaryError):
        resolve_allowed_path(
            str(outside),
            workspace=ws,
            allowed_root=ws,
        )


def test_restrict_to_workspace_blocks_outside_when_no_root(tmp_path: Path) -> None:
    """B3: ``restrict_to_workspace=True`` blocks outside paths even without an explicit root (B3)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("nope")
    with pytest.raises(WorkspaceBoundaryError):
        resolve_allowed_path(
            str(outside),
            workspace=ws,
            allowed_root=None,
            restrict_to_workspace=True,
        )


def test_restrict_to_workspace_allows_inside(tmp_path: Path) -> None:
    """B3: ``restrict_to_workspace=True`` allows paths inside the workspace (B3)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    inside = ws / "ok.txt"
    inside.write_text("ok")
    out = resolve_allowed_path(
        str(inside),
        workspace=ws,
        allowed_root=None,
        restrict_to_workspace=True,
    )
    assert out == inside.resolve()


def test_no_restriction_still_permissive(tmp_path: Path) -> None:
    """B3: without ``restrict_to_workspace`` and no ``allowed_root``, no containment check (escape hatch)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("free world")
    # No restrict_to_workspace, no allowed_root: still allowed.
    out = resolve_allowed_path(
        str(outside),
        workspace=ws,
        allowed_root=None,
        restrict_to_workspace=False,
    )
    assert out == outside.resolve()


def test_restrict_to_workspace_with_extra_roots(tmp_path: Path) -> None:
    """B3: ``extra_allowed_roots`` is honored alongside the implicit workspace root (B3)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    extra = tmp_path / "extra"
    extra.mkdir()
    extra_file = extra / "x.txt"
    extra_file.write_text("x")
    # ``extra_file`` is in ``extra_allowed_roots`` but NOT in ``ws``;
    # with ``restrict_to_workspace=True`` and no explicit ``allowed_root``,
    # the workspace is the implicit root, but ``extra_file`` is still
    # accepted via ``extra_allowed_roots``.
    out = resolve_allowed_path(
        str(extra_file),
        workspace=ws,
        allowed_root=None,
        extra_allowed_roots=[extra],
        restrict_to_workspace=True,
    )
    assert out == extra_file.resolve()
