"""Femtobot CLI plugin system.

Inspired by Claude Code plugin system:
FEMTOBOT_CLI_REFACTOR_PLAN.md Camada 3, T3.7.
"""

from femtobot.cli.plugins.loader import PluginLoader, PluginSpec
from femtobot.cli.plugins.registry import PluginRegistry

__all__ = ["PluginLoader", "PluginRegistry", "PluginSpec"]
