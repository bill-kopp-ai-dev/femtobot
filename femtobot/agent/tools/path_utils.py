"""Shared path helpers for workspace-scoped tools."""

from pathlib import Path

from femtobot.config.loader import get_instance_dir
from femtobot.config.paths import get_media_dir
from femtobot.security.workspace_policy import (
    is_path_within,
    resolve_allowed_path,
)


def get_project_root() -> Path | None:
    """Return the project root that contains the Femtobot ``.femtobot`` instance.

    The Femtobot instance directory lives at ``<project_root>/.femtobot``,
    and the agent workspace lives at ``<project_root>/.femtobot/workspace``
    — but that workspace is
    where the agent stores its own notes, memory and goals, **not** the
    user's source tree.

    Tools that operate on the user's project (e.g. ``exec``, ``read_file``,
    ``find_files``, ``grep``) should anchor their default ``cwd`` /
    relative-path resolution on this project root, not on the Femtobot
    workspace, so that ``ls femtobot/agent`` from the agent resolves to
    ``<project_root>/femtobot/agent`` and not to
    ``<project_root>/.femtobot/workspace/femtobot/agent``.

    Returns ``None`` when the instance dir cannot be discovered (the
    caller should then fall back to the existing ``workspace`` anchor).
    """
    instance_dir = get_instance_dir()
    # ``.femtobot`` / ``.femtobot_<suffix>`` always lives at the project
    # root, never nested deeper — see ``discover_instance_dir``.
    parent = instance_dir.parent
    if parent == instance_dir:
        return None
    return parent


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


def resolve_default_cwd(
    *,
    workspace: Path | None,
    restrict_to_workspace: bool,
) -> Path:
    """Return the default ``cwd`` for tools that anchor on the filesystem.

    Behaviour (audit for the E2E regression in v0.1.3 ninth-pass):

    * When ``restrict_to_workspace`` is True, the workspace itself is the
      anchor — there is nowhere else the agent is allowed to be.  This
      preserves the pre-fix sandbox-like semantics.
    * When ``restrict_to_workspace`` is False (the default for Femtobot
      installs), the agent's effective ``cwd`` should be the **project
      root** (the directory that contains ``.femtobot``), not the Femtobot
      workspace.  Otherwise commands like ``ls femtobot/agent`` resolve to
      ``.femtobot/workspace/femtobot/agent`` and silently miss the user's
      source tree, which is the failure mode reported by the E2E
      regression prompt.
    * Falls back to ``workspace`` if the project root cannot be
      discovered (e.g. legacy test harnesses that don't go through
      ``discover_instance_dir``).
    """
    if restrict_to_workspace and workspace is not None:
        return workspace
    project_root = get_project_root()
    if project_root is not None:
        return project_root
    return workspace  # type: ignore[return-value]
