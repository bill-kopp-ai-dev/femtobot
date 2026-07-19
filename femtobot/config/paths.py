"""Runtime path helpers derived from the active config context."""

from __future__ import annotations

from pathlib import Path

from femtobot.utils.helpers import ensure_dir


def get_data_dir() -> Path:
    """Return the instance-level runtime data directory."""
    from femtobot.config.loader import get_instance_dir

    return ensure_dir(get_instance_dir())


def get_runtime_subdir(name: str) -> Path:
    """Return a named runtime subdirectory under the instance data dir."""
    return ensure_dir(get_data_dir() / name)


def get_media_dir(channel: str | None = None) -> Path:
    """Return the media directory, optionally namespaced per channel."""
    base = get_runtime_subdir("media")
    return ensure_dir(base / channel) if channel else base


def get_workspace_path(workspace: str | None = None) -> Path:
    """Resolve and ensure the agent workspace path.

    If workspace is relative (e.g. 'workspace'), resolve relative to instance_dir.
    If workspace is absolute, use it directly.
    """
    from femtobot.config.loader import get_instance_dir

    if workspace:
        path = Path(workspace).expanduser()
        if path.is_absolute():
            return ensure_dir(path)
        # Relative path - resolve from instance_dir
        return ensure_dir(get_instance_dir() / path)

    # Default: workspace inside instance_dir
    return ensure_dir(get_instance_dir() / "workspace")


def get_memory_dir() -> Path:
    """Return the memory directory under workspace."""
    return ensure_dir(get_workspace_path() / "memory")


def get_sessions_dir() -> Path:
    """Return the sessions directory under workspace."""
    return ensure_dir(get_workspace_path() / "sessions")


def get_tool_results_dir(session_key: str | None = None) -> Path:
    """Return the tool results directory, optionally namespaced per session."""
    base = get_workspace_path() / "tool_results"
    return ensure_dir(base / session_key) if session_key else ensure_dir(base)


def get_artifacts_dir() -> Path:
    """Return the artifacts directory."""
    return ensure_dir(get_workspace_path() / "artifacts")


def get_templates_dir() -> Path:
    """Return the templates directory."""
    return ensure_dir(get_workspace_path() / ".templates")


def get_soul_path() -> Path:
    """Return the SOUL.md file path."""
    return get_workspace_path() / "SOUL.md"


def get_user_path() -> Path:
    """Return the USER.md file path."""
    return get_workspace_path() / "USER.md"


def is_default_workspace(workspace: str | Path | None) -> bool:
    """Return whether a workspace resolves to the instance's default workspace."""
    current = Path(workspace).expanduser() if workspace is not None else get_workspace_path()
    default = get_workspace_path()  # Uses instance_dir internally
    return current.resolve(strict=False) == default.resolve(strict=False)


def get_cli_history_path() -> Path:
    """Return the shared CLI history file path."""
    from femtobot.config.loader import get_instance_dir

    return get_instance_dir() / "history" / "cli_history"


def get_logs_dir() -> Path:
    """Return the instance-level runtime logs directory.

    Used for routing stderr from child processes (MCP stdio servers,
    long-task workers, etc.) into per-process files instead of
    inheriting the femtobot's own stderr. Without this, MCP server
    logs ``INFO mcp.server.lowlevel.server: Processing request of
    type CallToolRequest`` pollute the interactive TUI and get
    interleaved with user input — see ``longlogs.txt`` 2026-07-19
    issue #1, B2.
    """
    return get_runtime_subdir("logs")


def get_legacy_sessions_dir() -> Path:
    """Return the legacy global session directory used for migration fallback."""
    from femtobot.config.loader import get_instance_dir

    return get_instance_dir() / "sessions"
