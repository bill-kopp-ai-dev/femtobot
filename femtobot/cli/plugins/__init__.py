"""Femtobot CLI plugin system.

Inspired by Claude Code plugin system:
FEMTOBOT_CLI_REFACTOR_PLAN.md Camada 3, T3.7.
"""

from .loader import PluginLoader, PluginSpec
from .registry import PluginRegistry

__all__ = ["PluginLoader", "PluginRegistry", "PluginSpec"]
