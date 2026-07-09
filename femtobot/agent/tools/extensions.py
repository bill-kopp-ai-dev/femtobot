"""Local extension registry (C3).

C3 (REFACTOR_PLAN.md Lote C): femtobot is strongly MCP-centric, but
embedders occasionally need to declare a non-MCP extension — a local
script, an external CLI, a small HTTP service.  This module reads an
``extensions.json`` file from the instance folder and exposes the
declarations as a list of :class:`ExtensionConfig` records.  The CLI
tool surface (``femtobot tools list``, ``/extensions status``) consumes
this list to render / dispatch extensions.

The schema is intentionally simple::

    {
      "extensions": {
        "<name>": {
          "kind": "cli" | "http",
          "command": "...",      # for kind=cli
          "args": ["..."],       # optional, for kind=cli
          "url": "...",          # for kind=http
          "capabilities": ["..."]
        }
      }
    }

Validation is performed with the same fail-soft pattern as
``config.json``: a malformed file logs at ``error`` level (Lote A
strict mode) and returns ``[]`` so a typo doesn't take down the loop.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

_EXTENSION_KINDS = frozenset({"cli", "http"})


@dataclass(slots=True)
class ExtensionConfig:
    """One local extension declaration (C3)."""

    name: str
    kind: str  # "cli" or "http"
    command: str | None = None
    args: list[str] = field(default_factory=list)
    url: str | None = None
    capabilities: list[str] = field(default_factory=list)
    raw: dict | None = None  # original JSON object for debugging

    def is_valid(self) -> bool:
        """Return True when the declared shape matches *kind*."""
        if self.kind == "cli":
            return bool(self.command)
        if self.kind == "http":
            return bool(self.url)
        return False


def _coerce_extension(name: str, raw: object) -> ExtensionConfig | None:
    """Build an :class:`ExtensionConfig` from a JSON object; return None on bad shape."""
    if not isinstance(raw, dict):
        logger.error("Extension {!r} must be an object; got {}", name, type(raw).__name__)
        return None
    kind = raw.get("kind")
    if not isinstance(kind, str) or kind not in _EXTENSION_KINDS:
        logger.error(
            "Extension {!r}: 'kind' must be one of {}; got {!r}",
            name,
            sorted(_EXTENSION_KINDS),
            kind,
        )
        return None
    caps_raw = raw.get("capabilities") or []
    capabilities: list[str] = []
    if isinstance(caps_raw, list):
        capabilities = [str(c) for c in caps_raw if isinstance(c, (str, int))]
    elif isinstance(caps_raw, str):
        capabilities = [caps_raw]
    cfg = ExtensionConfig(
        name=name,
        kind=kind,
        command=raw.get("command") if isinstance(raw.get("command"), str) else None,
        url=raw.get("url") if isinstance(raw.get("url"), str) else None,
        args=[str(a) for a in (raw.get("args") or []) if isinstance(a, (str, int))],
        capabilities=capabilities,
        raw=raw,
    )
    if not cfg.is_valid():
        logger.error(
            "Extension {!r} (kind={}) is missing required field "
            "(cli→'command' or http→'url')",
            name,
            kind,
        )
        return None
    return cfg


def load_extensions(instance_dir: Path) -> list[ExtensionConfig]:
    """Read ``extensions.json`` from *instance_dir* and return a sorted list (C3).

    Returns an empty list when the file doesn't exist (the most
    common case: a vanilla install).  A malformed file is logged at
    ``error`` level and the function returns an empty list — the
    agent loop must keep running.
    """
    path = instance_dir / "extensions.json"
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        logger.error("extensions.json is not valid JSON ({}); ignoring", exc)
        return []
    except OSError as exc:
        logger.error("extensions.json could not be read: {}; ignoring", exc)
        return []

    exts_raw = data.get("extensions") if isinstance(data, dict) else None
    if not isinstance(exts_raw, dict):
        logger.error(
            "extensions.json: top-level 'extensions' must be an object mapping "
            "name -> definition; got {}",
            type(exts_raw).__name__,
        )
        return []

    out: list[ExtensionConfig] = []
    for name, raw in exts_raw.items():
        cfg = _coerce_extension(str(name), raw)
        if cfg is not None:
            out.append(cfg)
    out.sort(key=lambda c: c.name)
    return out
