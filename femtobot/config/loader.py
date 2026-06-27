"""Configuration loading utilities."""

import json
import os
import re
from pathlib import Path
from typing import Any

import pydantic
from loguru import logger
from pydantic import BaseModel

from femtobot.config.schema import Config, _resolve_tool_config_refs

# Global variable to store current config path (for multi-instance support)
_current_config_path: Path | None = None
_current_instance_dir: Path | None = None
_schema_refs_ready = False

_VALID_SUFFIX_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def set_config_path(path: Path) -> None:
    """Set the current config path (used to derive data directory)."""
    global _current_config_path
    _current_config_path = path
    # Also update instance_dir to parent of config
    global _current_instance_dir
    _current_instance_dir = path.parent


def get_config_path() -> Path:
    """Get the configuration file path."""
    if _current_config_path:
        return _current_config_path
    return get_instance_dir() / "config.json"


def build_instance_dir_name(suffix: str | None) -> str:
    """Build instance directory name: .femtobot or .femtobot_<suffix>."""
    if suffix:
        return f".femtobot_{suffix}"
    return ".femtobot"


def validate_instance_suffix(suffix: str | None) -> str | None:
    """Validate and normalize instance suffix. Returns None for invalid suffixes."""
    if suffix is None:
        return None
    if not suffix or not _VALID_SUFFIX_PATTERN.match(suffix):
        return None
    return suffix


def set_instance_dir(path: Path) -> None:
    """Set the current instance directory (used to derive all data paths)."""
    global _current_config_path
    global _current_instance_dir
    _current_instance_dir = path
    # Also update config path to point to config.json inside instance_dir
    _current_config_path = path / "config.json"


def get_instance_dir() -> Path:
    """Get the current instance directory.

    Precedence:
    1. Explicitly set instance_dir
    2. FEMTOBOT_HOME environment variable
    3. Auto-discovery in cwd or parent
    """
    if _current_instance_dir:
        return _current_instance_dir

    # Check FEMTOBOT_HOME environment variable
    env_home = os.environ.get("FEMTOBOT_HOME")
    if env_home:
        return Path(env_home)

    # Auto-discovery (discover_instance_dir is defined in this module)
    return discover_instance_dir()


def clear_instance_dir() -> None:
    """Clear the current instance directory (for testing and reuse)."""
    global _current_instance_dir
    _current_instance_dir = None


def resolve_instance_dir(folder_path: Path | None = None, suffix: str | None = None) -> Path:
    """Resolve the instance directory path.

    Args:
        folder_path: Parent directory where instance dir should be created/found.
                     If None, uses cwd.
        suffix: Instance suffix. If None, uses default ".femtobot".

    Returns:
        Full path to the instance directory.
    """
    # Validate suffix
    validated_suffix = validate_instance_suffix(suffix)
    instance_name = build_instance_dir_name(validated_suffix)

    if folder_path:
        return folder_path / instance_name

    # Default: use parent of project directory
    from pathlib import Path

    cwd = Path.cwd()

    # If cwd is inside a project subdir (like femtobot/), go up one level
    if cwd.name in ("femtobot", "femtobot", "src", "agent"):
        return cwd.parent / instance_name

    return cwd / instance_name


def discover_instance_dir(start: Path | None = None, suffix: str | None = None) -> Path:
    """Discover an existing instance directory.

    Args:
        start: Directory to start searching from. Defaults to resolved project root.
        suffix: If provided, look for .femtobot_<suffix>. Otherwise look for .femtobot.

    Returns:
        Path to the discovered instance directory.
        Returns resolved instance_dir if none found (assumes it will be created there).
    """
    from pathlib import Path

    # Determine the base search directory
    if start is None:
        cwd = Path.cwd()
        # If cwd is inside a project subdir (like femtobot/), search from parent
        if cwd.name in ("femtobot", "femtobot", "src", "agent"):
            start = cwd.parent
        else:
            start = cwd

    # Build the instance name we're looking for
    validated_suffix = validate_instance_suffix(suffix)
    instance_name = build_instance_dir_name(validated_suffix)

    # Search in start and its parent
    for base in [start, start.parent]:
        candidate = base / instance_name
        if candidate.is_dir():
            return candidate

    # Also search in cwd if start is not cwd
    if start != Path.cwd():
        cwd = Path.cwd()
        if cwd.name in ("femtobot", "femtobot", "src", "agent"):
            candidate = cwd.parent / instance_name
            if candidate.is_dir():
                return candidate

    # Return resolved instance_dir as fallback (assumes it will be created there)
    return resolve_instance_dir(folder_path=None, suffix=suffix)


def resolve_runtime_location(
    config_path: Path | None, folder_path: Path | None, suffix: str | None
) -> None:
    """Resolve and set the runtime location for the agent.

    Call this before load_config() to ensure correct instance is used.
    For runtime commands (status, agent, gateway), uses discover_instance_dir
    to find an existing instance.
    For onboard, use resolve_instance_dir directly.
    """
    if config_path:
        # Legacy: --config specified
        set_config_path(config_path)
    else:
        # For runtime commands, discover the existing instance
        instance_dir = discover_instance_dir(
            start=Path(folder_path) if folder_path else None, suffix=suffix
        )
        set_instance_dir(instance_dir)


def load_config(config_path: Path | None = None) -> Config:
    """
    Load configuration from file or create default.

    Args:
        config_path: Optional path to config file. Uses default if not provided.

    Returns:
        Loaded configuration object.
    """
    global _schema_refs_ready
    if not _schema_refs_ready:
        _resolve_tool_config_refs()
        _schema_refs_ready = True

    # Load a gitignored ``.env`` from the active instance directory before
    # constructing ``Config`` so ``BaseSettings`` picks up
    # ``FEMTOBOT_PROVIDERS__<NAME>__API_KEY`` etc. via its env-prefix + nested
    # delimiter machinery. ``.env`` values never override explicit shell env
    # vars (override=False).
    _load_instance_env_file()

    path = config_path or get_config_path()

    config = Config()
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            data = _migrate_config(data)
            config = Config.model_validate(data)
        except (json.JSONDecodeError, ValueError, pydantic.ValidationError) as e:
            logger.warning("Failed to load config from {}: {}", path, e)
            logger.warning("Using default configuration.")

    _apply_ssrf_whitelist(config)
    return config


def _apply_ssrf_whitelist(config: Config) -> None:
    """Apply SSRF whitelist from config to the network security module."""
    from femtobot.security.network import configure_ssrf_whitelist

    configure_ssrf_whitelist(config.tools.ssrf_whitelist)


def _load_instance_env_file() -> Path | None:
    """Load a ``.env`` file co-located with the active instance directory.

    Behavior:
        * Looks for ``<instance_dir>/.env`` and, if absent, falls back to
          ``<cwd>/.env`` (so shells running from the project root still work).
        * Loads values into ``os.environ`` using ``python-dotenv``'s
          ``load_dotenv`` with ``override=False`` — explicit env vars already
          set by the user/IDE always win.
        * Idempotent and safe to call multiple times.

    Returns:
        The path that was loaded, or ``None`` if no ``.env`` was found.

    Notes:
        * ``.env`` is already covered by the instance ``.gitignore`` (see
          ``Femtobot — instance, runtime and workspace data`` block) so the
          loaded secrets are never tracked by git.
        * Use the convention ``FEMTOBOT_PROVIDERS__<NAME>__API_KEY`` (e.g.
          ``FEMTOBOT_PROVIDERS__MINIMAX__API_KEY``) to inject provider
          credentials; ``Config`` is a ``BaseSettings`` with
          ``env_prefix="FEMTOBOT_"`` and ``env_nested_delimiter="__"``.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - python-dotenv is a hard dependency
        return None

    instance_dir = get_instance_dir()
    candidates: list[Path] = []
    if instance_dir is not None:
        candidates.append(instance_dir / ".env")
    try:
        cwd = Path.cwd()
    except OSError:  # pragma: no cover - extremely defensive
        cwd = None
    if cwd is not None:
        candidates.append(cwd / ".env")

    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        if resolved in seen:
            continue
        seen.add(resolved)
        if candidate.is_file():
            # ``override=False`` keeps explicit shell/IDE env vars authoritative.
            load_dotenv(candidate, override=False, encoding="utf-8")
            return candidate
    return None


def save_config(
    config: Config,
    config_path: Path | None = None,
    *,
    scrub_secrets: bool = True,
) -> None:
    """Save configuration to file.

    SECURITY: by default, sensitive fields (``api_key``, ``token``, ``secret``,
    etc.) are scrubbed to ``None`` before persistence. See
    ``femtobot.utils.secret_scrub`` for the catalog and rationale. Pass
    ``scrub_secrets=False`` to persist verbatim — this re-opens the on-disk
    exposure the scrubber is meant to close, so use it only when you fully
    trust the destination path.

    Args:
        config: Configuration to save.
        config_path: Optional path to save to. Uses default if not provided.
        scrub_secrets: When True (default), sensitive values are replaced with
            ``None`` before serialization.
    """
    from loguru import logger

    from femtobot.utils.secret_scrub import count_secrets, scrub_secrets as _scrub

    path = config_path or get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(mode="json", by_alias=True)
    secret_count = count_secrets(data)
    if secret_count > 0:
        logger.warning(
            "Config at {} contains {} sensitive field(s) (api_key/token/secret/...). "
            "Move them to env vars (FEMTOBOT_PROVIDERS__<NAME>__API_KEY) or a "
            "gitignored .env file. They will be scrubbed from the persisted "
            "config.json to avoid leaking via `git add` / backups / IDE sync.",
            path,
            secret_count,
        )

    if scrub_secrets:
        data, _ = _scrub(data)
    elif secret_count > 0:
        logger.warning(
            "Persisting {} sensitive field(s) to {} with scrub_secrets=False. "
            "This file MUST stay out of version control.",
            secret_count,
            path,
        )

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


_ENV_REF_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def resolve_config_env_vars(config: Config) -> Config:
    """Return *config* with ``${VAR}`` env-var references resolved.

    Walks in place so fields declared with ``exclude=True`` survive;
    returns the same instance when no references are present.
    Raises ``ValueError`` if a referenced variable is not set.
    """
    return _resolve_in_place(config)


def _resolve_in_place(obj: Any) -> Any:
    if isinstance(obj, str):
        new = _ENV_REF_PATTERN.sub(_env_replace, obj)
        return new if new != obj else obj
    if isinstance(obj, BaseModel):
        updates: dict[str, Any] = {}
        for name in type(obj).model_fields:
            old = getattr(obj, name)
            new = _resolve_in_place(old)
            if new is not old:
                updates[name] = new
        extras = obj.__pydantic_extra__
        new_extras: dict[str, Any] | None = None
        if extras:
            resolved = {k: _resolve_in_place(v) for k, v in extras.items()}
            if any(resolved[k] is not extras[k] for k in extras):
                new_extras = resolved
        if not updates and new_extras is None:
            return obj
        copy = obj.model_copy(update=updates) if updates else obj.model_copy()
        if new_extras is not None:
            copy.__pydantic_extra__ = new_extras
        return copy
    if isinstance(obj, dict):
        resolved = {k: _resolve_in_place(v) for k, v in obj.items()}
        return resolved if any(resolved[k] is not obj[k] for k in obj) else obj
    if isinstance(obj, list):
        resolved = [_resolve_in_place(v) for v in obj]
        return resolved if any(nv is not ov for nv, ov in zip(resolved, obj)) else obj
    return obj


def _resolve_env_vars(obj: object) -> object:
    """Recursively resolve ``${VAR}`` patterns in plain strings/dicts/lists."""
    if isinstance(obj, str):
        return _ENV_REF_PATTERN.sub(_env_replace, obj)
    if isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_vars(v) for v in obj]
    return obj


def _env_replace(match: re.Match[str]) -> str:
    name = match.group(1)
    value = os.environ.get(name)
    if value is None:
        raise ValueError(f"Environment variable '{name}' referenced in config is not set")
    return value


def _migrate_config(data: dict) -> dict:
    """Migrate old config formats to current."""
    # Move tools.exec.restrictToWorkspace → tools.restrictToWorkspace
    tools = data.get("tools", {})
    exec_cfg = tools.get("exec", {})
    if "restrictToWorkspace" in exec_cfg and "restrictToWorkspace" not in tools:
        tools["restrictToWorkspace"] = exec_cfg.pop("restrictToWorkspace")

    # Move tools.myEnabled / tools.mySet → tools.my.{enable, allowSet}.
    # The old flat keys shipped in the initial MyTool landing; wrapping them in a
    # sub-config keeps `web` / `exec` / `my` symmetric and gives room to grow.
    if "myEnabled" in tools or "mySet" in tools:
        my_cfg = tools.setdefault("my", {})
        if "myEnabled" in tools and "enable" not in my_cfg:
            my_cfg["enable"] = tools.pop("myEnabled")
        else:
            tools.pop("myEnabled", None)
        if "mySet" in tools and "allowSet" not in my_cfg:
            my_cfg["allowSet"] = tools.pop("mySet")
        else:
            tools.pop("mySet", None)

    return data
