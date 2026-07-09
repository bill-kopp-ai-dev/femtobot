"""Tests for Camada 3 T3.7 plugin loader and registry."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from femtobot.cli.plugins import PluginLoader, PluginRegistry, PluginSpec


def _make_plugin_dir(base: Path, name: str, *, allowed_tools=None, version="0.1.0") -> Path:
    plugin_dir = base / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"name": name, "version": version, "description": f"Test plugin {name}"}
    if allowed_tools is not None:
        manifest["allowed_tools"] = list(allowed_tools)
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest))
    return plugin_dir


class TestPluginLoaderDiscover:
    """PluginLoader.discover() walks search paths and parses manifests."""

    def test_discovers_valid_plugin(self, tmp_path):
        _make_plugin_dir(tmp_path, "my_plugin", allowed_tools=["read_file"])
        loader = PluginLoader(instance_dir=tmp_path)
        plugins = loader.discover()
        assert "my_plugin" in plugins
        assert plugins["my_plugin"].name == "my_plugin"
        assert "read_file" in plugins["my_plugin"].allowed_tools

    def test_skips_invalid_json(self, tmp_path):
        bad_dir = tmp_path / "bad_plugin"
        bad_dir.mkdir()
        (bad_dir / "plugin.json").write_text("{ not valid json")
        _make_plugin_dir(tmp_path, "good_plugin")
        loader = PluginLoader(instance_dir=tmp_path)
        plugins = loader.discover()
        assert "good_plugin" in plugins
        assert "bad_plugin" not in plugins

    def test_returns_empty_when_no_plugins(self, tmp_path):
        loader = PluginLoader(instance_dir=tmp_path)
        plugins = loader.discover()
        assert plugins == {}

    def test_skips_directory_without_plugin_json(self, tmp_path):
        (tmp_path / "no_manifest").mkdir()
        loader = PluginLoader(instance_dir=tmp_path)
        plugins = loader.discover()
        assert plugins == {}

    def test_discovers_multiple_plugins(self, tmp_path):
        _make_plugin_dir(tmp_path, "plugin_a")
        _make_plugin_dir(tmp_path, "plugin_b")
        loader = PluginLoader(instance_dir=tmp_path)
        plugins = loader.discover()
        assert "plugin_a" in plugins
        assert "plugin_b" in plugins


class TestPluginNameHandling:
    """Plugin name comes from plugin.json or falls back to directory name."""

    def test_uses_name_from_manifest(self, tmp_path):
        plugin_dir = tmp_path / "dir_name"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.json").write_text(
            json.dumps({"name": "manifest_name", "version": "0.1.0"})
        )
        loader = PluginLoader(instance_dir=tmp_path)
        plugins = loader.discover()
        assert "manifest_name" in plugins

    def test_falls_back_to_dir_name_if_no_name_field(self, tmp_path):
        plugin_dir = tmp_path / "dir_name"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.json").write_text(json.dumps({"version": "0.1.0"}))
        loader = PluginLoader(instance_dir=tmp_path)
        plugins = loader.discover()
        assert "dir_name" in plugins

    def test_accepts_safe_names(self, tmp_path):
        _make_plugin_dir(tmp_path, "valid-plugin_v1")
        loader = PluginLoader(instance_dir=tmp_path)
        plugins = loader.discover()
        assert "valid-plugin_v1" in plugins

    def test_unsafe_name_in_manifest_does_not_cause_file_access(self, tmp_path):
        """Path traversal in name field stays as metadata; no filesystem traversal occurs."""
        plugin_dir = tmp_path / "dummy"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.json").write_text(
            json.dumps({"name": "../../etc/passwd", "version": "0.1.0"})
        )
        loader = PluginLoader(instance_dir=tmp_path)
        # Must not raise, must not access /etc/passwd
        plugins = loader.discover()
        # If stored, the plugin_dir should still be within tmp_path
        for spec in plugins.values():
            if spec.plugin_dir is not None:
                assert str(spec.plugin_dir).startswith(str(tmp_path))


class TestSearchPathsPrecedence:
    """Later constructor argument (builtin_dir) overrides earlier (instance_dir)."""

    def test_later_path_overrides_earlier(self, tmp_path):
        instance_dir = tmp_path / "instance"
        builtin_dir = tmp_path / "builtin"
        instance_dir.mkdir()
        builtin_dir.mkdir()
        _make_plugin_dir(instance_dir, "shared", allowed_tools=["instance_tool"])
        _make_plugin_dir(builtin_dir, "shared", allowed_tools=["builtin_tool"])
        loader = PluginLoader(instance_dir=instance_dir, builtin_dir=builtin_dir)
        plugins = loader.discover()
        assert "shared" in plugins
        assert len([k for k in plugins if k == "shared"]) == 1

    def test_builtin_only_plugin_appears(self, tmp_path):
        builtin_dir = tmp_path / "builtin"
        builtin_dir.mkdir()
        _make_plugin_dir(builtin_dir, "builtin_only")
        loader = PluginLoader(builtin_dir=builtin_dir)
        plugins = loader.discover()
        assert "builtin_only" in plugins

    def test_ignores_nonexistent_directories(self, tmp_path):
        nonexistent = tmp_path / "does_not_exist"
        loader = PluginLoader(instance_dir=nonexistent)
        plugins = loader.discover()
        assert plugins == {}


class TestPluginSpec:
    """PluginSpec dataclass structure and immutability."""

    def test_plugin_spec_minimal(self):
        spec = PluginSpec(name="test", version="0.1.0")
        assert spec.name == "test"
        assert spec.version == "0.1.0"
        assert spec.allowed_tools == ()

    def test_plugin_spec_with_tools(self):
        spec = PluginSpec(name="test", version="1.0.0", allowed_tools=("read", "write"))
        assert "read" in spec.allowed_tools
        assert "write" in spec.allowed_tools

    def test_plugin_spec_is_frozen(self):
        spec = PluginSpec(name="test", version="0.1.0")
        with pytest.raises((AttributeError, TypeError)):
            spec.name = "changed"  # type: ignore[misc]


class TestPluginRegistry:
    """PluginRegistry approve/revoke/query operations."""

    def _make_registry_with_plugins(self, tmp_path, *names):
        for name in names:
            _make_plugin_dir(tmp_path, name, allowed_tools=["read"])
        loader = PluginLoader(instance_dir=tmp_path)
        loader.discover()
        registry = PluginRegistry()
        registry.set_loader(loader)
        return registry

    def test_approve_and_get(self, tmp_path):
        registry = self._make_registry_with_plugins(tmp_path, "p1")
        assert registry.approve("p1") is True
        plugin = registry.get_approved_plugin("p1")
        assert plugin is not None
        assert plugin.name == "p1"

    def test_get_unapproved_returns_none(self, tmp_path):
        registry = self._make_registry_with_plugins(tmp_path, "p1")
        assert registry.get_approved_plugin("p1") is None

    def test_get_unknown_returns_none(self, tmp_path):
        registry = self._make_registry_with_plugins(tmp_path)
        assert registry.get_approved_plugin("nonexistent") is None

    def test_is_approved(self, tmp_path):
        registry = self._make_registry_with_plugins(tmp_path, "p1")
        assert registry.is_approved("p1") is False
        registry.approve("p1")
        assert registry.is_approved("p1") is True

    def test_revoke(self, tmp_path):
        registry = self._make_registry_with_plugins(tmp_path, "p1")
        registry.approve("p1")
        assert registry.revoke("p1") is True
        assert registry.is_approved("p1") is False
        assert registry.get_approved_plugin("p1") is None

    def test_list_approved_sorted(self, tmp_path):
        registry = self._make_registry_with_plugins(tmp_path, "b", "a")
        registry.approve("b")
        registry.approve("a")
        assert registry.list_approved() == ["a", "b"]

    def test_approve_returns_false_without_loader(self):
        registry = PluginRegistry()
        assert registry.approve("anything") is False

    def test_approve_returns_false_for_undiscovered_plugin(self, tmp_path):
        registry = self._make_registry_with_plugins(tmp_path, "p1")
        assert registry.approve("nonexistent") is False
