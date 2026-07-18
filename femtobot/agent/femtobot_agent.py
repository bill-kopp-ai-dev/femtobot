"""FemtobotAgent: PydanticAI-backed agent factory.

Femtobot 1.0 builds its core agent on top of pydantic_ai.Agent. This
module exposes:

  - FemtobotAgent: thin wrapper holding the configured pydantic_ai.Agent
  - build_system_prompt(): composes AGENTS.md + SOUL.md + USER.md +
    skills + memory excerpt

Femtobot 0.1.x still works (AgentLoop is untouched). FemtobotAgent is
the replacement that will be wired in at Phase 4.

See docs/architecture.md (post-1.0) for the full design.

Phase 1 (current): only the four native provider types are wired.
For Phase 1 we resolve ``agents.defaults.provider`` (a string like
``"openai"`` or ``"anthropic"``) into the matching
``ProvidersConfig.<name>`` entry and let ``_build_model`` pick the
PydanticAI Model. Phase 5 adds fallback / multi-provider rotation.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, TYPE_CHECKING

import pydantic_ai
from pydantic_ai.models import Model
from pydantic_ai.tools import Tool

from femtobot.agent.deps import FemtobotDeps
from femtobot.agent.output import FemtobotOutput

if TYPE_CHECKING:
    from femtobot.config.schema import Config


# Providers we know how to dispatch to PydanticAI native Model classes.
# Anything not in this map is treated as OpenAI-compat (custom field).
_NATIVE_PROVIDERS: frozenset[str] = frozenset({"openai", "anthropic", "bedrock", "gemini"})


def _resolve_provider_name(config: "Config") -> str:
    """Pick the active provider name from ``agents.defaults.provider``.

    ``"auto"`` falls back to the first configured provider with an
    API key set (matches the legacy AgentLoop behavior at a high
    level; full parity arrives in Phase 5).
    """
    name = (config.agents.defaults.provider or "auto").strip().lower()
    if name != "auto":
        return name
    # Auto-detection: scan providers in order, return the first one
    # with an api_key. We deliberately do NOT honor provider
    # precedence from the legacy AgentLoop here — that's a Phase 5
    # concern. For Phase 1 the goal is "wires up", not "wires up
    # optimally".
    for prov_name in config.providers.__class__.model_fields:
        prov = getattr(config.providers, prov_name, None)
        if prov is None:
            continue
        if getattr(prov, "api_key", None):
            return prov_name
    return "openai"  # last-resort default; will surface a clean error in _build_model


def _build_model(config: "Config") -> Model:
    """Resolve the configured provider into a PydanticAI Model.

    Phase 1 supports the four native types. The OpenAI-compat bucket
    is routed through ``OpenAIModel`` with a custom ``base_url``;
    this collapses Zhipu / DashScope / DeepSeek / Groq / etc. into a
    single code path. Phase 5 introduces a separate
    ``OpenAICompatModel`` wrapper if dedicated features surface.
    """
    from pydantic_ai.models.openai import OpenAIModel
    from pydantic_ai.providers.openai import OpenAIProvider

    name = _resolve_provider_name(config)
    provider_cfg = getattr(config.providers, name, None)
    if provider_cfg is None:
        raise ValueError(f"Unknown provider {name!r} in agents.defaults.provider")

    model_name = config.agents.defaults.model

    # Native OpenAI (or anything we treat as OpenAI-compat for Phase 1).
    if name in _NATIVE_PROVIDERS - {"anthropic", "bedrock", "gemini"} or name not in {
        "anthropic",
        "bedrock",
        "gemini",
    }:
        provider_kwargs: dict[str, Any] = {}
        if getattr(provider_cfg, "api_key", None):
            provider_kwargs["api_key"] = provider_cfg.api_key
        if getattr(provider_cfg, "api_base", None):
            provider_kwargs["base_url"] = provider_cfg.api_base
        return OpenAIModel(
            model_name,
            provider=OpenAIProvider(**provider_kwargs) if provider_kwargs else None,
        )

    # The remaining three native types arrive in Phase 5. Raising
    # here with a clear message lets users temporarily route through
    # ``provider = "openai"`` + ``api_base`` without losing data.
    raise NotImplementedError(
        f"Provider type {name!r} is not yet wired into the PydanticAI adapter. "
        "Open the model in Phase 5 or set agents.defaults.provider to 'openai' "
        "with the upstream API base as a temporary workaround."
    )


def build_system_prompt(config: "Config", workspace: Path) -> str:
    """Compose the system prompt from AGENTS.md + skills + memory.

    This delegates to the existing ContextBuilder for the heavy
    lifting; only the *output* is sent to PydanticAI's
    ``system_prompt`` rather than inserted as the first model
    message.

    Note: ContextBuilder expects a bus ``InboundMessage`` to size
    template snippets. We synthesize a minimal system-channel one
    to avoid pulling in the loop machinery.
    """
    from femtobot.agent.context import ContextBuilder
    from femtobot.bus.events import InboundMessage

    builder = ContextBuilder(config, workspace)
    inbound = InboundMessage(
        channel="cli",
        sender_id="system",
        chat_id="direct",
        content="",
    )
    messages = builder.build_messages(inbound, include_history=False)
    for msg in messages:
        if msg.get("role") == "system":
            content = msg.get("content", "")
            return content if isinstance(content, str) else str(content)
    return ""


class FemtobotAgent:
    """A configured PydanticAI agent.

    Construction is lazy: the underlying ``pydantic_ai.Agent`` is
    built on first access so that import-time failures (e.g. missing
    API key) do not block ``femtobot --help``.
    """

    def __init__(
        self,
        config: "Config",
        workspace: Path,
        *,
        tools: list[Tool] | None = None,
        use_combined_toolset: bool = False,
    ) -> None:
        self._config = config
        self._workspace = workspace
        # If ``use_combined_toolset=True``, ignore the explicit ``tools``
        # argument and pull every migrated toolset via
        # ``femtobot.agent.toolsets.combined_toolset``. The default is
        # ``False`` so existing callers that pass ``tools=...`` keep
        # working unchanged.
        if use_combined_toolset:
            from femtobot.agent.toolsets._combined import combined_toolset

            self._tools = combined_toolset(config)
        else:
            self._tools = tools or []
        # Generic ``Agent[DepsT, OutputT]`` is parameterized with our
        # ``FemtobotDeps``/``FemtobotOutput`` types; the annotation is
        # intentionally ``Any`` to keep the class body import-light
        # (PydanticAI's generic eagerly resolves the params otherwise).
        self._agent: Any = None

    @classmethod
    def from_config(
        cls,
        config: "Config",
        workspace: Path,
        *,
        tools: list[Tool] | None = None,
    ) -> "FemtobotAgent":
        """Build a FemtobotAgent from the active config.

        Equivalent to ``cls(config, workspace, tools=...)`` but makes
        the call site explicit and matches the signature planned for
        Phase 4 (which adds session_manager).
        """
        return cls(config=config, workspace=workspace, tools=tools)

    @property
    def agent(self) -> Any:
        if self._agent is None:
            self._agent = pydantic_ai.Agent(
                _build_model(self._config),
                deps_type=FemtobotDeps,
                output_type=FemtobotOutput,
                system_prompt=build_system_prompt(self._config, self._workspace),
                tools=self._tools,
            )
        return self._agent

    def rebuild(self) -> None:
        """Force a rebuild on next ``.agent`` access. Used after config changes."""
        self._agent = None

    async def run(self, message: str, deps: FemtobotDeps) -> FemtobotOutput:
        result = await self.agent.run(message, deps=deps)
        return result.output

    async def run_stream(self, message: str, deps: FemtobotDeps) -> AsyncIterator[Any]:
        """Yield streamed text deltas followed by the final FemtobotOutput.

        Uses ``Agent.run_stream()`` — the standard PydanticAI
        streaming entrypoint. The CLI's render_streamed() consumes
        this iterator (Phase 2).
        """
        async with self.agent.run_stream(message, deps=deps) as streamed:
            async for chunk in streamed.stream_text(delta=True):
                yield chunk
            yield streamed.result.output


__all__ = ["FemtobotAgent", "build_system_prompt"]
