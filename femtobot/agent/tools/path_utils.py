"""Shared path helpers for workspace-scoped tools."""

from pathlib import Path

from femtobot.config.paths import get_media_dir
from femtobot.security.workspace_policy import (
    is_path_within,
    resolve_allowed_path,
)


def is_under(path: Path, directory: Path) -> bool:
    """Return True when path resolves under directory."""
    return is_path_within(path, directory)


def resolve_workspace_path(
    path: str,
    workspace: Path | None = None,
    allowed_dir: Path | None = None,
    extra_allowed_dirs: list[Path] | None = None,
    restrict_to_workspace: bool = False,
) -> Path:
    """Resolve path against workspace and enforce allowed directory containment.

    Audit (B3 of the v0.0.8 third-pass review): the helper now
    forwards ``restrict_to_workspace`` to ``resolve_allowed_path``
    so a tool that doesn't pass an explicit ``allowed_dir`` still
    gets containment enforcement when the tool's policy says
    "restrict to workspace".  This closes the path-traversal hole
    that let a tool read ``/etc/passwd`` from a missing-policy
    tool.
    """
    extra_roots = [get_media_dir(), *(extra_allowed_dirs or [])] if allowed_dir else None
    return resolve_allowed_path(
        path,
        workspace=workspace,
        allowed_root=allowed_dir,
        extra_allowed_roots=extra_roots,
        restrict_to_workspace=restrict_to_workspace,
    )
