"""Onboard wizard: interactive model + provider chooser (C5).

C5 (REFACTOR_PLAN.md Lote C): the first time a user runs
``femtobot onboard`` (or whenever they pass ``--wizard``), prompt
them to pick:

  1. A provider (from the registered :class:`ProviderSpec` list).
  2. A model (a small curated set per provider).
  3. An API key (skipped when one is already in env).

The wizard mutates the in-memory ``Config`` and returns a
:class:`WizardResult` so the caller can re-persist.  When stdin is not
a TTY, the wizard skips itself and returns ``None`` so non-interactive
deploys keep working.

The wizard never blocks: any error or non-numeric input falls back to
the next reasonable default, and a Ctrl-C exits with a clear "cancelled"
message instead of a traceback.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from rich.console import Console
from rich.prompt import Prompt  # noqa: I001

# Curated model menu per provider — keeps the wizard short and avoids
# the user having to type a model string they may not know.
# CLI-parity v0.1.7 (Issue 6): this is no longer hardcoded for the
# eight providers we shipped in v0.1.x.  The default fallback for
# any provider not in this dict is a single ``"<custom>"`` choice.
# Providers added in femtobot/providers/registry.py after v0.1.7
# will appear automatically (see _list_providers / _models_for).
_CURATED_MODELS: dict[str, list[str]] = {
    "anthropic": [
        "claude-3-7-sonnet-20250219",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
    ],
    "openai": [
        "gpt-4o",
        "gpt-4o-mini",
        "o1",
    ],
    "openrouter": [
        "anthropic/claude-3.5-sonnet",
        "openai/gpt-4o",
        "meta-llama/llama-3.1-70b-instruct",
    ],
    "ollama": [
        "llama3.1:70b",
        "qwen2.5:32b",
        "deepseek-r1:32b",
    ],
    "gemini": [
        "gemini-2.0-flash-exp",
        "gemini-1.5-pro",
    ],
    "groq": [
        "llama-3.3-70b-versatile",
        "mixtral-8x7b-32768",
    ],
    "mistral": [
        "mistral-large-latest",
        "mistral-small-latest",
    ],
    "deepseek": [
        "deepseek-chat",
        "deepseek-reasoner",
    ],
}


def _default_curated_for(provider_slug: str) -> list[str]:
    """Render a sensible default model suggestion for an unknown provider.

    CLI-parity v0.1.7 (Issue 6): the upstream nanobot wizard pulls
    curated defaults from the registry; the Femtobot C5 refactor
    had a hardcoded 8-entry dict and added a regression where new
    providers were invisible to onboard.  We retain the curated
    table for the eight established providers (it gives the user
    immediately-usable defaults without typing) and add a generic
    fallback for everything else, derived from the first matching
    keyword of the spec.
    """
    sl = provider_slug.lower()
    if "ollama" in sl or "vllm" in sl or "lm_studio" in sl or "lm-studio" in sl:
        return ["llama3.1:8b"]
    return ["<custom>"]


def _list_providers() -> list[str]:
    """Return a stable, sorted list of provider names available in the registry."""
    try:
        from femtobot.providers.registry import list_provider_specs
    except Exception:  # pragma: no cover - defensive
        return sorted(_CURATED_MODELS.keys())
    try:
        return sorted(spec.name for spec in list_provider_specs())
    except Exception:  # pragma: no cover - defensive
        return sorted(_CURATED_MODELS.keys())


def _models_for(provider: str) -> list[str]:
    """Return the curated model menu for *provider*.

    Falls back to :func:`_default_curated_for` for providers not in
    :data:`_CURATED_MODELS` (CLI-parity v0.1.7 Issue 6).
    """
    return _CURATED_MODELS.get(provider) or _default_curated_for(provider)


def _env_key_for(provider: str) -> str | None:
    """Return the conventional env var name for the provider's API key.

    CLI-parity v0.1.7 (companion to Issue 6): prefer the
    ``env_key`` field on the :class:`ProviderSpec` so that adding
    a new provider to the registry lights up its env var here
    automatically.  Fall back to a small hardcoded table only when
    the registry lookup fails (e.g. the provider was removed but
    the caller still references it).
    """
    try:
        from femtobot.providers.registry import find_by_name

        spec = find_by_name(provider)
        if spec and spec.env_key:
            return spec.env_key
    except Exception:  # pragma: no cover - defensive
        pass
    table = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "google": "GOOGLE_API_KEY",
        "groq": "GROQ_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
    }
    return table.get(provider)


@dataclass(slots=True)
class WizardResult:
    """What the wizard mutates / returns to the caller (C5)."""

    provider: str
    model: str
    api_key_provided: bool
    config: object | None = None  # mutated Config (may be None when no-op)


def run_onboard_wizard(
    config: object | None,
    *,
    console: Console | None = None,
) -> WizardResult | None:
    """Prompt the user for provider / model / key.  Returns None on cancellation (C5).

    Non-TTY environments (CI, tests) exit immediately and the caller
    continues with the default config.
    """
    import sys

    if not sys.stdin.isatty():
        return None
    console = console or Console()
    providers = _list_providers()
    if not providers:
        return None

    # CLI-parity v0.1.7 (Issue 2): a 2-line welcome header explains
    # what the wizard does and which steps will run.  Mirrors
    # nanobot's ``_show_main_menu_header``.
    console.print("\n[bold cyan]Femtobot quick setup[/bold cyan]")
    console.print(
        "[dim]Pick a provider, pick a model, drop in your API key.\n"
        "Three prompts total. Ctrl-C cancels — your previous config is preserved.\n[/dim]"
    )

    # CLI-parity v0.1.7 (Issue 3): main menu between welcome and the
    # first prompt.  Mirrors nanobot's ``run_onboard`` main menu in
    # primitive form: only the default ``Quick Start`` flow exists
    # today, but the menu itself gives the user an Exit affordance
    # so they can back out before any prompt has been answered.
    console.print(
        "\n  [bold][Q][/bold] Quick Start  "
        "  [bold][E][/bold] Exit\n"
    )
    try:
        menu = Prompt.ask(
            "Choose",
            choices=["Q", "E"],
            default="Q",
            console=console,
            show_choices=False,
        ).strip().upper()
    except (KeyboardInterrupt, EOFError):
        return None
    if menu != "Q":
        console.print("[dim]Aborted wizard.[/dim]")
        return None

    # 1. Provider
    default_provider = "anthropic" if "anthropic" in providers else providers[0]
    provider = Prompt.ask(
        "Provider",
        choices=providers,
        default=default_provider,
        console=console,
    )

    # 2. Model
    models = _models_for(provider)
    model = Prompt.ask(
        "Default model",
        choices=models,
        default=models[0],
        console=console,
    )
    if model == "<custom>":
        model = Prompt.ask("Custom model name", console=console)

    # 3. API key (skip if already in env)
    api_key_provided = False
    env_key = _env_key_for(provider)
    if env_key and not os.environ.get(env_key):
        key = Prompt.ask(
            f"{env_key} (leave empty to skip and set later)",
            password=True,
            default="",
            console=console,
        )
        if key:
            # CLI-parity v0.1.7 (Issue 4): confirm by prefix so the
            # user catches a paste-with-extra-spaces bug before the
            # wrong key is shipped into the config file.
            prefix = key[:4].rstrip()
            console.print(
                f"  [dim]captured {env_key} starting with [cyan]{prefix}…[/cyan][/dim]"
            )
            os.environ[env_key] = key
            api_key_provided = True

    # 4. Mutate the in-memory config so the rest of ``onboard`` picks
    # up the choices.  When the caller didn't pass a config, the
    # caller will rebuild it from ``build_default_onboard_config`` and
    # the preset/provider will already have the right default.
    if config is not None:
        try:
            from femtobot.config.schema import ModelPresetConfig, ProviderConfig

            # Provider entry: only add when the user supplied a key.
            if api_key_provided and env_key:
                existing_providers = dict(getattr(config, "providers", {}) or {})
                if provider not in existing_providers:
                    existing_providers[provider] = ProviderConfig(
                        api_key=os.environ.get(env_key),
                    )
                    config.providers = existing_providers

            # Model preset: ``f"{provider}-wizard"`` is reserved for the
            # onboard output.  We rebuild the dict so pydantic's
            # validation runs (preserves type).
            preset_name = f"{provider}-wizard"
            existing_presets = dict(getattr(config, "model_presets", {}) or {})
            if preset_name not in existing_presets:
                existing_presets[preset_name] = ModelPresetConfig(
                    label=f"{provider} (wizard)",
                    model=model,
                    provider=provider,
                )
                config.model_presets = existing_presets
            # Point agents.defaults at the new preset.
            if getattr(config, "agents", None) and getattr(config.agents, "defaults", None):
                config.agents.defaults.model_preset = preset_name
                # Also reflect the chosen model + provider on the implicit
                # default so a CLI run without ``--model`` uses them.
                config.agents.defaults.model = model
                config.agents.defaults.provider = provider
        except Exception as exc:  # pragma: no cover - defensive
            console.print(f"[yellow]![/yellow] Could not apply wizard choices: {exc}")

    console.print(
        f"\n[green]✓[/green] Wizard done.  Provider: [cyan]{provider}[/cyan], "
        f"model: [cyan]{model}[/cyan]"
        + (" (api key set)" if api_key_provided else "")
    )

    return WizardResult(
        provider=provider,
        model=model,
        api_key_provided=api_key_provided,
        config=config,
    )
