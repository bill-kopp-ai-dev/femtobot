"""Plugin registry — tracks approved/loaded plugins at runtime."""

from __future__ import annotations

from .loader import PluginLoader, PluginSpec


class PluginRegistry:
    """Runtime registry of approved plugins.

    Plugins must be approved via `/plugin approve <name>` before they
    can be loaded. This prevents arbitrary code execution from
    untrusted plugin directories.
    """

    def __init__(self):
        self._loader: PluginLoader | None = None
        self._approved: set[str] = set()
        self._loaded: dict[str, PluginSpec] = {}

    def set_loader(self, loader: PluginLoader) -> None:
        self._loader = loader

    def approve(self, name: str) -> bool:
        """Mark a plugin as approved. Returns True if plugin was found."""
        if self._loader is None:
            return False
        plugin = self._loader.get_plugin(name)
        if plugin is None:
            return False
        self._approved.add(name)
        self._loaded[name] = plugin
        return True

    def revoke(self, name: str) -> bool:
        """Remove a plugin from the approved list."""
        self._approved.discard(name)
        return self._loaded.pop(name, None) is not None

    def is_approved(self, name: str) -> bool:
        return name in self._approved

    def list_approved(self) -> list[str]:
        return sorted(self._approved)

    def get_approved_plugin(self, name: str) -> PluginSpec | None:
        if not self.is_approved(name):
            return None
        return self._loaded.get(name)
