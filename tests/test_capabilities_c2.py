"""Capabilities / tool registry filter tests (C2)."""

from __future__ import annotations

import pytest

from femtobot.agent.tools.base import Tool
from femtobot.agent.tools.registry import ToolRegistry

pytestmark = pytest.mark.architecture


class _ReadTool(Tool):
    capabilities = ["read-only", "fast"]
    read_only = True

    @property
    def name(self) -> str:
        return "fake_read"

    @property
    def description(self) -> str:
        return "fake read tool"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs):  # pragma: no cover - unused
        return "ok"


class _WriteTool(Tool):
    capabilities = ["needs-confirmation"]

    @property
    def name(self) -> str:
        return "fake_write"

    @property
    def description(self) -> str:
        return "fake write tool"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs):  # pragma: no cover - unused
        return "ok"


def test_get_capabilities_includes_read_only_from_property() -> None:
    """C2: read_only=True surfaces ``read-only`` in get_capabilities() (C2)."""
    tool = _ReadTool()
    caps = tool.get_capabilities()
    assert "read-only" in caps
    # ``read-only`` should not be duplicated when both class attr and
    # property produce it.
    assert caps.count("read-only") == 1


def test_get_capabilities_returns_class_list() -> None:
    """C2: a tool with only class-level capabilities returns them unchanged (C2)."""
    tool = _WriteTool()
    caps = tool.get_capabilities()
    assert caps == ["needs-confirmation"]


def test_has_capability() -> None:
    """C2: ``has_capability`` returns the right boolean (C2)."""
    tool = _ReadTool()
    assert tool.has_capability("read-only") is True
    assert tool.has_capability("needs-confirmation") is False


def test_registry_by_capability() -> None:
    """C2: ``ToolRegistry.by_capability`` returns only matching tools (C2)."""
    registry = ToolRegistry()
    registry.register(_ReadTool())
    registry.register(_WriteTool())
    read_only = registry.by_capability("read-only")
    assert [t.name for t in read_only] == ["fake_read"]
    confirm = registry.by_capability("needs-confirmation")
    assert [t.name for t in confirm] == ["fake_write"]


def test_registry_by_capability_empty_returns_empty() -> None:
    """C2: empty / None capability returns an empty list (C2)."""
    registry = ToolRegistry()
    registry.register(_ReadTool())
    assert registry.by_capability("") == []
    assert registry.by_capability(None) == []


def test_registry_by_capability_unknown_returns_empty() -> None:
    """C2: an unknown capability returns an empty list (C2)."""
    registry = ToolRegistry()
    registry.register(_ReadTool())
    assert registry.by_capability("nonexistent-capability") == []


def test_registry_capabilities_summary() -> None:
    """C2: ``ToolRegistry.capabilities()`` returns a map of capability → tool names (C2)."""
    registry = ToolRegistry()
    registry.register(_ReadTool())
    registry.register(_WriteTool())
    summary = registry.capabilities()
    # Tool names within each capability are sorted.
    assert summary["read-only"] == ["fake_read"]
    assert summary["fast"] == ["fake_read"]
    assert summary["needs-confirmation"] == ["fake_write"]
    # All keys are strings.
    assert all(isinstance(k, str) for k in summary.keys())
