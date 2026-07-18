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


def resolve_instance_dir(folder_path: Path | None = None) -> Path:
    """Resolve the instance directory path.

    Args:
        folder_path: Parent directory where instance dir should be created/found.
                     If None, uses cwd.

    Returns:
        Full path to the instance directory.
    """
    instance_name = ".femtobot"

    if folder_path:
        return folder_path / instance_name

    # Default: use parent of project directory
    from pathlib import Path

    cwd = Path.cwd()

    # If cwd is inside a project subdir (like femtobot/), go up one level
    if cwd.name in ("femtobot", "femtobot", "src", "agent"):
        return cwd.parent / instance_name

    return cwd / instance_name


def discover_instance_dir(start: Path | None = None) -> Path:
    """Discover an existing instance directory.

    Args:
        start: Directory to start searching from. Defaults to resolved project root.

    Returns:
        Path to the discovered instance directory.
        Returns resolved instance_dir if none found (assumes it will be created there).
    """
    from pathlib import Path

    instance_name = ".femtobot"

    # Determine the base search directory
    if start is None:
        cwd = Path.cwd()
        # If cwd is inside a project subdir (like femtobot/), search from parent
        if cwd.name in ("femtobot", "femtobot", "src", "agent"):
            start = cwd.parent
        else:
            start = cwd

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
    return resolve_instance_dir(folder_path=None)


def resolve_runtime_location(
    config_path: Path | None, folder_path: Path | None
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
            start=Path(folder_path) if folder_path else None
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
            # Important: ``Config.model_validate(data)`` does NOT re-read
            # ``os.environ`` — it constructs the object purely from ``data``.
            # That means a config.json with ``apiKey: null`` (the correct
            # scrubbed shape) would silently wipe the credentials we just
            # loaded from the gitignored ``.env``. To preserve env-var
            # precedence for fields the JSON left blank, fold any
            # ``FEMTOBOT_*`` env vars whose leaf is currently null/empty into
            # the dict before validation.
            data = _merge_env_overrides(data)
            config = Config.model_validate(data)
        except json.JSONDecodeError as e:
            _handle_config_load_error(
                path, e, kind="json", strict=_is_strict_config_load()
            )
        except pydantic.ValidationError as e:
            _handle_config_load_error(
                path, e, kind="validation", strict=_is_strict_config_load()
            )
        except ValueError as e:
            _handle_config_load_error(
                path, e, kind="value", strict=_is_strict_config_load()
            )

    _apply_ssrf_whitelist(config)
    return config


def _is_strict_config_load() -> bool:
    """Return True when fail-fast on invalid config is enabled.

    Gated by ``FEMTOBOT_STRICT_CONFIG_LOAD`` (default ``false`` in v0.0.3 for
    backward compat; planned to default ``true`` in v0.0.4).  See
    ``REFACTOR_PLAN.md`` Lote A / item A1.
    """
    raw = os.environ.get("FEMTOBOT_STRICT_CONFIG_LOAD", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _handle_config_load_error(
    path: Path, exc: BaseException, *, kind: str, strict: bool
) -> None:
    """Centralized handler for config-load failures.

    - Strict mode: abort with a loud, actionable message (exit code 2) so
      silent fallbacks can't mask typos / missing fields.
    - Lenient mode (default): keep the historical ``logger.warning`` path so
      existing deployments are not broken, but escalate to ``logger.error``
      for JSON syntax errors and required-field ValidationErrors where a
      silent default would be actively dangerous.
    """
    if strict:
        location = getattr(exc, "loc", None)
        path_hint = ""
        if location:
            path_hint = f" (field: {'.'.join(str(p) for p in location)})"
        msg = (
            f"Failed to load config from {path}: {kind} error{path_hint}: {exc}\n"
            f"Set FEMTOBOT_STRICT_CONFIG_LOAD=false to fall back to defaults, "
            f"or fix the config and retry."
        )
        logger.error(msg)
        raise SystemExit(2)
    if kind == "json":
        # JSON syntax errors are NEVER safe to silently swallow — the user
        # wrote bad JSON.  Stay loud (error-level) but don't crash.
        logger.error(
            "Failed to load config from {}: invalid JSON ({})", path, exc
        )
        logger.error("Using default configuration.")
    elif kind == "validation":
        location = getattr(exc, "loc", None)
        # Required-field errors (loc present, no clear default) escalate to
        # error; optional-field errors stay as warnings.
        if location and _is_required_validation_error(exc):
            logger.error(
                "Config at {} failed validation for required field '{}': {}",
                path,
                ".".join(str(p) for p in location),
                exc,
            )
        else:
            logger.warning("Failed to load config from {}: {}", path, exc)
        logger.warning("Using default configuration.")
    else:
        logger.warning("Failed to load config from {}: {}", path, exc)
        logger.warning("Using default configuration.")


def _is_required_validation_error(exc: pydantic.ValidationError) -> bool:
    """Heuristic: a missing-type error on a top-level field is 'required'."""
    for err in exc.errors():
        if err.get("type") == "missing":
            loc = err.get("loc") or ()
            # Top-level required field — depth 1 (e.g. ('providers',))
            if len(loc) == 1:
                return True
    return False


def validate_config(
    config_path: Path | None = None, *, strict: bool | None = None
) -> tuple[bool, str]:
    """Validate a config without entering the agent loop.

    Honors ``FEMTOBOT_STRICT_CONFIG_LOAD`` when ``strict`` is None.  Returns
    ``(ok, message)``.  Used by the ``femtobot config validate`` CLI subcommand
    (A1).
    """
    if strict is None:
        strict = _is_strict_config_load()
    saved = os.environ.get("FEMTOBOT_STRICT_CONFIG_LOAD")
    if strict:
        os.environ["FEMTOBOT_STRICT_CONFIG_LOAD"] = "1"
    else:
        os.environ.pop("FEMTOBOT_STRICT_CONFIG_LOAD", None)
    try:
        # Force a fresh load (loader caches state via _schema_refs_ready).
        global _schema_refs_ready
        _schema_refs_ready = False
        load_config(config_path=config_path)
    except SystemExit as e:
        return False, f"Config validation failed (exit {e.code})"
    except Exception as e:  # pragma: no cover - defensive
        return False, f"Config validation errored: {e}"
    finally:
        if saved is None:
            os.environ.pop("FEMTOBOT_STRICT_CONFIG_LOAD", None)
        else:
            os.environ["FEMTOBOT_STRICT_CONFIG_LOAD"] = saved
    mode = "strict" if strict else "lenient"
    return True, f"Config OK ({mode})"


def _known_config_paths() -> set[tuple[str, ...]]:
    """Return the set of valid ``FEMTOBOT_*`` env-var paths for the active Config.

    Walk ``Config.model_fields`` recursively and collect the path tuples
    (lowercased) that ``BaseSettings`` would accept via
    ``env_prefix="FEMTOBOT_"`` + ``env_nested_delimiter="__"``. The set is
    built lazily and cached for the lifetime of the process.

    Why this exists: ``FEMTOBOT_*`` is overloaded — it carries both
    ``Config`` fields (e.g. ``FEMTOBOT_PROVIDERS__MINIMAX__API_KEY``) and
    feature flags read directly via ``os.environ.get`` (e.g.
    ``FEMTOBOT_LOGFIRE``, ``FEMTOBOT_LOGFIRE_HTTPX``). Without filtering,
    ``_merge_env_overrides`` happily injects the flag as a synthetic field,
    which the ``Config`` ``extra="forbid"`` policy then rejects — masking
    the real config with a "Using default configuration" fallback.
    """
    cache_key = "_known_config_paths_cache"
    cached = globals().get(cache_key)
    if cached is not None:
        return cached

    paths: set[tuple[str, ...]] = set()
    stack: list[tuple[BaseModel, tuple[str, ...]]] = [(Config, ())]
    while stack:
        model, prefix = stack.pop()
        for name, field in model.model_fields.items():
            current = prefix + (name,)
            paths.add(current)
            # Descend into nested BaseModel fields. Skip container-like
            # fields (dict / list) and scalars — they are leaves.
            annotation = field.annotation
            if annotation is None:
                continue
            try:
                nested_type = annotation.__args__[0] if hasattr(annotation, "__args__") else annotation
            except (AttributeError, IndexError):
                nested_type = annotation
            if isinstance(nested_type, type) and issubclass(nested_type, BaseModel):
                stack.append((nested_type, current))
    globals()[cache_key] = paths
    return paths


def _merge_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """Return ``data`` with ``FEMTOBOT_*`` env vars patched in for null leaves.

    Translates the env-var convention used by ``Config`` (``BaseSettings``)
    — ``env_prefix="FEMTOBOT_"`` + ``env_nested_delimiter="__"`` — back into
    nested dict keys and overlays them on top of ``data``. The merge is
    shallow-by-level but walks dicts recursively so e.g.
    ``FEMTOBOT_PROVIDERS__MINIMAX__API_KEY`` lands at
    ``data["providers"]["minimax"]["api_key"]``.

    Rules:
        * Only leaves that are ``None``, ``""`` or missing in ``data`` are
          overridden. Explicit non-null values in the JSON win (intentional:
          the user wrote them in the file, so they take precedence).
        * Strings are not case-folded — the env var names already match the
          model field names (``API_KEY`` -> ``api_key``).
        * Empty string env values are skipped (a bare ``KEY=`` line would
          otherwise clobber a configured non-null value).
        * Env vars whose path does not correspond to a known ``Config``
          field are silently skipped (logged at debug). This protects the
          shared ``FEMTOBOT_*`` namespace from feature flags like
          ``FEMTOBOT_LOGFIRE`` that are read directly via ``os.environ.get``
          and must not be coerced into synthetic ``Config`` fields.

    This is the seam that lets the ``.env`` feed secrets into ``Config``
    even though the on-disk ``config.json`` deliberately keeps
    ``providers.*.apiKey`` as ``null`` for safety.
    """
    if not isinstance(data, dict):
        return data

    prefix = "FEMTOBOT_"
    known_paths = _known_config_paths()
    for env_name, env_value in os.environ.items():
        if not env_name.startswith(prefix):
            continue
        if env_value == "":
            continue
        path = env_name[len(prefix):].split("__")
        if not path:
            continue
        # Lowercase only the top-level segment to match Pydantic's
        # ``populate_by_name`` behavior with the camelCase aliases. The
        # `to_camel` alias generator produces `apiKey` while the env var
        # carries `API_KEY`; both must reach the same field.
        path = [path[0].lower(), *(p.lower() for p in path[1:])]
        # Skip feature flags and other namespace-shared vars that aren't
        # actual Config fields. Without this guard, ``FEMTOBOT_LOGFIRE=1``
        # would be coerced into ``data["logfire"] = "1"`` and the
        # ``extra="forbid"`` policy on Config would reject the entire
        # load, silently falling back to the hardcoded defaults.
        if tuple(path) not in known_paths:
            logger.debug(
                "Skipping FEMTOBOT_* env var {} (not a Config field); "
                "read it via os.environ.get if you need it.",
                env_name,
            )
            continue
        _set_if_blank(data, path, env_value)
    return data


def _set_if_blank(node: Any, path: list[str], value: str) -> None:
    """Recursively descend ``path`` and set ``value`` only at blank leaves.

    At the leaf, both the snake_case name (``api_key``) and the camelCase
    alias produced by ``to_camel`` (``apiKey``) are checked — the env-var
    convention is always snake_case/upper, but the on-disk JSON uses
    whichever the user (or the default dumper) chose. If either key exists
    and is ``None``/empty, the existing key is overwritten in place (no
    duplicate keys created). If neither exists yet, ``api_key`` is created.
    """
    if not path:
        return
    head, *tail = path
    if tail:
        child = node.get(head) if isinstance(node, dict) else None
        if not isinstance(child, dict):
            return  # Refuse to descend through scalars/None — env vars
            # cannot create new sub-trees that the JSON didn't already
            # sketch out.
        _set_if_blank(child, tail, value)
        return

    if not isinstance(node, dict):
        return

    camel = _snake_to_camel(head)
    for candidate in (head, camel):
        if candidate in node:
            current = node[candidate]
            if current is None or current == "":
                node[candidate] = value
            return  # First match wins — never duplicate the key.
    # Neither snake nor camel existed: create the snake_case form.
    node[head] = value


def _snake_to_camel(name: str) -> str:
    """Convert ``api_key`` -> ``apiKey`` to match the Pydantic alias generator."""
    parts = name.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


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

    from femtobot.utils.secret_scrub import count_secrets
    from femtobot.utils.secret_scrub import scrub_secrets as _scrub

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

    # R2-femtobot (refactor-parity-with-nanobot.md Phase 6): the default
    # of ``restrict_to_workspace`` flipped from False to True.  Migrate
    # legacy configs that explicitly opted out (False) so the new
    # safety posture takes effect on existing instances — operators
    # who really need the old "full host shell" behaviour can set
    # the field back to False after the migration runs (it is a
    # no-op on subsequent loads).
    if tools.get("restrictToWorkspace") is False:
        tools["restrictToWorkspace"] = True

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
