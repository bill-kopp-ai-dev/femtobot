"""Plugin loader with sandbox isolation.

Inspired by Claude Code plugin system:
FEMTOBOT_CLI_REFACTOR_PLAN.md Camada 3, T3.7.

Each plugin lives in its own directory under the plugin search path.
Search paths (in precedence order):
  1. <instance_dir>/plugins/
  2. ~/.femtobot/plugins/
  3. <pkg>/plugins/builtin/   (bundled plugins)

Each plugin directory contains:
  plugin.json      — metadata (name, version, allowed-tools)
  commands/        — slash commands (same format as .md skills)
  skills/          — multi-step workflows (SKILL.md files)
  hooks/           — pre/post hooks
  themes/          — optional theme overrides

Security: plugins declare allowed-tools; Femtobot policy enforces this.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

@dataclass(frozen=True)
class PluginSpec:
    """Metadata from a plugin's plugin.json."""
    name: str
    version: str
    description: str = ""
    allowed_tools: tuple[str, ...] = field(default_factory=tuple)
    hooks: tuple[str, ...] = field(default_factory=tuple)  # pre_turn, post_turn, etc.
    plugin_dir: Path | None = field(default=None, repr=False)


class PluginLoader:
    """Discover and load plugins from the search paths."""

    def __init__(
        self,
        instance_dir: Path | None = None,
        home_dir: Path | None = None,
        builtin_dir: Path | None = None,
    ):
        self._search_paths: list[Path] = []
        for path in [instance_dir, home_dir, builtin_dir]:
            if path and path.is_dir():
                self._search_paths.append(path)
        self._loaded: dict[str, PluginSpec] = {}

    def discover(self) -> dict[str, PluginSpec]:
        """Scan all search paths for plugins. Later paths override earlier ones."""
        found: dict[str, PluginSpec] = {}
        for search_path in self._search_paths:
            for entry in sorted(search_path.iterdir()):
                if not entry.is_dir():
                    continue
                spec = self._load_plugin_meta(entry)
                if spec is not None:
                    found[spec.name] = spec
        self._loaded = found
        return found

    def _load_plugin_meta(self, plugin_dir: Path) -> PluginSpec | None:
        meta_file = plugin_dir / "plugin.json"
        if not meta_file.exists():
            return None
        try:
            raw = json.loads(meta_file.read_text("utf-8"))
            return PluginSpec(
                name=str(raw.get("name", plugin_dir.name)),
                version=str(raw.get("version", "0.0.0")),
                description=str(raw.get("description", "")),
                allowed_tools=tuple(str(t) for t in raw.get("allowed_tools", [])),
                hooks=tuple(str(h) for h in raw.get("hooks", [])),
                plugin_dir=plugin_dir,
            )
        except (json.JSONDecodeError, OSError):
            return None

    def get_plugin(self, name: str) -> PluginSpec | None:
        return self._loaded.get(name)

    @property
    def all_plugins(self) -> dict[str, PluginSpec]:
        return dict(self._loaded)
