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
from typing import TYPE_CHECKING, Any, AsyncIterator

import pydantic_ai
from pydantic_ai.models import Model
from pydantic_ai.tools import Tool

from femtobot.agent.deps import FemtobotDeps
from femtobot.agent.output import FemtobotOutput

if TYPE_CHECKING:
    from femtobot.config.schema import Config


# Providers we know how to dispatch to PydanticAI native Model classes.
# Anything not in this set is treated as OpenAI-compat (custom field
# with a base_url). Keeping this in a single source of truth makes it
# easy to add a new native provider (e.g. "mistral") without missing
# any dispatch sites.
_NATIVE_PROVIDERS: frozenset[str] = frozenset({"openai", "anthropic", "bedrock", "gemini"})
# The subset that has its own PydanticAI Model class (not OpenAI-compat).
_NON_OPENAI_NATIVE: frozenset[str] = _NATIVE_PROVIDERS - {"openai"}


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

    Phase 5 (current) supports the four native types
    (openai / anthropic / bedrock / gemini) plus a unified
    OpenAI-compat bucket that covers the 24 regional providers
    (Zhipu, DashScope, DeepSeek, Groq, etc.) by routing them
    through ``OpenAIModel`` with a custom ``base_url``.

    Missing optional SDKs (anthropic / boto3 / google-genai) surface
    as a clean ``RuntimeError`` pointing at the right ``uv add``
    command — we do NOT silently fall back to OpenAI because that
    would mask auth problems.
    """
    from pydantic_ai.models.openai import OpenAIModel
    from pydantic_ai.providers.openai import OpenAIProvider

    name = _resolve_provider_name(config)
    provider_cfg = getattr(config.providers, name, None)
    if provider_cfg is None:
        # Bug fix (re-audit 2026-07-18): the previous message omitted
        # the list of valid provider names, making typos hard to
        # debug. Include the canonical list so users can spot the
        # mistake immediately.
        known = sorted(config.providers.__class__.model_fields.keys())
        raise ValueError(
            f"Unknown provider {name!r} in agents.defaults.provider. "
            f"Available providers: {', '.join(known)}. "
            f"Either add providers.{name} to config.json or fix the typo."
        )

    model_name = config.agents.defaults.model

    # Native OpenAI (or anything we treat as OpenAI-compat).
    if name not in _NON_OPENAI_NATIVE:
        provider_kwargs: dict[str, Any] = {}
        if getattr(provider_cfg, "api_key", None):
            provider_kwargs["api_key"] = provider_cfg.api_key
        if getattr(provider_cfg, "api_base", None):
            provider_kwargs["base_url"] = provider_cfg.api_base
        # Bug fix (re-audit 2026-07-18): when neither api_key nor
        # api_base is set, ``OpenAIProvider()`` would be constructed
        # without credentials and the downstream OpenAI SDK would
        # raise a generic ``openai.OpenAIError`` ("The api_key
        # client option must be set..."). Surface an actionable
        # message instead, pointing at the right env vars.
        if not provider_kwargs:
            raise RuntimeError(
                f"Provider {name!r} has no api_key or api_base configured. "
                f"Set providers.{name}.api_key in config.json, or "
                f"export FEMTOBOT_PROVIDERS__{name.upper()}__API_KEY "
                "(or FEMTOBOT_PROVIDERS__CUSTOM__API_BASE for a "
                "self-hosted endpoint)."
            )
        return OpenAIModel(
            model_name,
            provider=OpenAIProvider(**provider_kwargs),
        )

    # Native Anthropic. Requires the optional ``anthropic`` SDK.
    if name == "anthropic":
        try:
            from pydantic_ai.models.anthropic import AnthropicModel
        except ImportError as exc:
            raise RuntimeError(
                "Provider 'anthropic' requires the anthropic SDK. "
                "Install with: uv add 'pydantic-ai-slim[anthropic]'"
            ) from exc
        provider_kwargs = {}
        if getattr(provider_cfg, "api_key", None):
            provider_kwargs["api_key"] = provider_cfg.api_key
        return AnthropicModel(model_name, **provider_kwargs)

    # Native Bedrock. Requires boto3.
    if name == "bedrock":
        try:
            from pydantic_ai.models.bedrock import BedrockConverseModel
        except ImportError as exc:
            raise RuntimeError(
                "Provider 'bedrock' requires boto3. "
                "Install with: uv add 'femtobot[bedrock]'"
            ) from exc
        return BedrockConverseModel(model_name)

    # Native Gemini. Requires the optional google-genai SDK.
    # PydanticAI 1.31 renamed GeminiModel → GoogleModel; fall back
    # to the deprecated alias if the new name is unavailable.
    if name == "gemini":
        try:
            from pydantic_ai.models.google import GoogleModel
            return GoogleModel(model_name)
        except ImportError:
            try:
                from pydantic_ai.models.gemini import GeminiModel  # type: ignore[no-redef]

                return GeminiModel(model_name)
            except ImportError as exc:
                raise RuntimeError(
                    "Provider 'gemini' requires the google-genai SDK. "
                    "Install with: uv add 'pydantic-ai-slim[gemini]'"
                ) from exc

    # Fallback guard for future additions to _NATIVE_PROVIDERS that
    # are not yet wired.
    raise NotImplementedError(
        f"Provider type {name!r} is not yet wired into the PydanticAI adapter. "
        "Set agents.defaults.provider to 'openai' with the upstream API base "
        "as a temporary workaround."
    )


# Minimal identity prompt used as a fallback when ContextBuilder is
# unavailable or returns no system message (e.g. brand-new workspace
# with no AGENTS.md/SOUL.md yet). Keeps the agent from running with
# zero identity.
_MINIMAL_FEMTOBOT_PROMPT = (
    "You are Femtobot, a minimalist CLI AI agent built on PydanticAI. "
    "You help the user with shell commands, file editing, web research, "
    "and tool use. Be concise and direct."
)


def build_system_prompt(config: "Config", workspace: Path) -> str:
    """Compose the system prompt from AGENTS.md + skills + memory.

    This delegates to the existing ContextBuilder for the heavy
    lifting; only the *output* is sent to PydanticAI's
    ``system_prompt`` rather than inserted as the first model
    message.

    Bug fix (re-audit 2026-07-18): the previous code returned the
    empty string when ContextBuilder had no system message (brand-new
    workspace, missing AGENTS.md, etc.), which left the agent running
    with no identity at all. We now fall back to a minimal identity
    prompt so the agent still has *some* baseline.
    """
    try:
        from femtobot.agent.context import ContextBuilder
        from femtobot.bus.events import InboundMessage
    except Exception:
        return _MINIMAL_FEMTOBOT_PROMPT

    builder = ContextBuilder(config, workspace)
    inbound = InboundMessage(
        channel="cli",
        sender_id="system",
        chat_id="direct",
        content="",
    )
    try:
        messages = builder.build_messages(inbound, include_history=False)
    except Exception:
        return _MINIMAL_FEMTOBOT_PROMPT
    for msg in messages:
        if msg.get("role") == "system":
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                return content
            return str(content) if content else _MINIMAL_FEMTOBOT_PROMPT
    return _MINIMAL_FEMTOBOT_PROMPT


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

        Note: ``async def`` + ``yield`` produces an async generator
        object directly (not a coroutine). Consumers should write
        ``async for chunk in agent.run_stream(...)`` without an
        explicit ``await``.
        """
        async with self.agent.run_stream(message, deps=deps) as streamed:
            async for chunk in streamed.stream_text(delta=True):
                yield chunk
            yield streamed.result.output


__all__ = ["FemtobotAgent", "build_system_prompt"]
