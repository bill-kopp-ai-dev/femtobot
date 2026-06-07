"""Configuration module for femtobot."""

from femtobot.config.loader import get_config_path, load_config
from femtobot.config.paths import (
    get_cli_history_path,
    get_data_dir,
    get_legacy_sessions_dir,
    get_media_dir,
    get_runtime_subdir,
    get_workspace_path,
    is_default_workspace,
)
from femtobot.config.schema import Config

__all__ = [
    "Config",
    "load_config",
    "get_config_path",
    "get_data_dir",
    "get_runtime_subdir",
    "get_media_dir",
    "get_workspace_path",
    "is_default_workspace",
    "get_cli_history_path",
    "get_legacy_sessions_dir",
]
