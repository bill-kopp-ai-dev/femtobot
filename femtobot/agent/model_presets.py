"""Helpers for runtime model preset selection."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from femtobot.config.schema import ModelPresetConfig
from femtobot.providers.base import LLMProvider
from femtobot.providers.factory import ProviderSnapshot

PresetSnapshotLoader = Callable[[str], ProviderSnapshot]


def configured_model_presets(config: Any) -> dict[str, ModelPresetConfig]:
    return {**config.model_presets, "default": config.resolve_default_preset()}


def build_static_preset_snapshot(
    provider: LLMProvider,
    name: str,
    preset: ModelPresetConfig,
) -> ProviderSnapshot:
    provider.generation = preset.to_generation_settings()
    return ProviderSnapshot(
        provider=provider,
        model=preset.model,
        context_window_tokens=preset.context_window_tokens,
        signature=("model_preset", name, preset.model_dump_json()),
    )


def build_runtime_preset_snapshot(
    *,
    name: str,
    presets: dict[str, ModelPresetConfig],
    provider: LLMProvider,
    loader: PresetSnapshotLoader | None,
) -> ProviderSnapshot:
    if loader is not None:
        return loader(name)
    return build_static_preset_snapshot(provider, name, presets[name])
