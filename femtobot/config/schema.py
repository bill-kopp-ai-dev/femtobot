"""Configuration schema using Pydantic."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel
from pydantic_settings import BaseSettings

if TYPE_CHECKING:
    from femtobot.agent.tools.self import MyToolConfig
    from femtobot.agent.tools.shell import ExecToolConfig
    from femtobot.agent.tools.web import WebToolsConfig


# ---------------------------------------------------------------------------
# CLI spacing defaults — single source of truth (Camada 4 / Camada 5)
# ---------------------------------------------------------------------------
# These constants are the canonical defaults for the per-turn CLI spacing
# knobs (``margin_x``, ``gap_after_turn``, ``role_header``, etc.). They are
# re-exported by ``femtobot.cli.role_renderer`` as aliases, so editing this
# block is the *only* place needed to change the runtime defaults — no more
# "I changed a constant and the CLI didn't budge" surprises.
#
# Override at runtime (highest priority first):
#   1. ``/style set margin_x=6 gap_after_turn=2`` (REPL, session-only)
#   2. env var — e.g. ``FEMTOBOT_AGENTS__DEFAULTS__CLI__MARGIN_X=6``
#   3. .env file co-located with the active instance
#   4. the schema defaults declared below
#
# Knob semantics (visual impact on the CLI REPL):
#
# :data:`CLI_DEFAULT_GAP_AFTER_TURN`
#     Blank lines printed *after* each completed agent turn. Gives the
#     terminal room to breathe between replies so the next ``You:``
#     prompt doesn't sit glued to the bottom of the previous answer.
#     Range: ``CLI_MIN_GAP``..``CLI_MAX_GAP`` (0..2).
#
# :data:`CLI_DEFAULT_ROLE_HEADER_MODE`
#     Visibility / style of the bar shown *before* each agent turn.
#     Three modes:
#       ``"always"``  — bold colored bar ``🤖 Femtobot ▌`` (default).
#       ``"minimal"`` — emoji only (legacy Camada 1 behavior).
#       ``"off"``     — no header at all (silent).
#
# :data:`CLI_DEFAULT_USER_SEPARATOR`
#     When ``True``, prints a thin dim divider line (``· · · ·``) right
#     after the user submits input, so the agent's reply is framed.
#     Set to ``False`` for a borderless conversation look.
#
# :data:`CLI_DEFAULT_MARGIN_X`
#     Horizontal padding (in chars) applied to the left *and* right of
#     every agent reply via ``rich.Padding``. Solves the "text glued to
#     terminal edges" complaint from P1. Range:
#     ``CLI_MIN_MARGIN``..``CLI_MAX_MARGIN`` (2..4).
#
# :data:`CLI_DEFAULT_GAP_BEFORE_INPUT`
#     Extra blank lines printed *before* the ``You:`` prompt. Gives the
#     user visual space to read the last reply before starting to type.
#     Range: ``CLI_MIN_INPUT_GAP``..``CLI_MAX_INPUT_GAP`` (0..4).
#
# :data:`CLI_DEFAULT_TURN_BOX`
#     When ``True``, the role headers are rendered as bracketed boxes
#     (``[🤖 Femtobot]`` for the agent, ``[👤 You]`` for the user).
#     Each turn becomes a visually distinct block, solving the
#     "agent/human indistinguishable" complaint from P3. Set to
#     ``False`` for the legacy bar + plain ``You:`` style.
# ---------------------------------------------------------------------------

# -- Per-turn gaps ---------------------------------------------------------
# Each constant has a paired comment describing its semantics, visual
# impact, and range. Module-level ``__doc__`` is not preserved for
# primitive literals (Python rebinds ``int.__doc__`` / ``str.__doc__``
# at import time), so the per-constant docs live as side-comments
# instead. The matching fields on :class:`CliConfig` carry the same
# descriptions via Pydantic ``Field(description=...)`` so they show up
# in JSON schemas and IDE tooltips.

CLI_DEFAULT_GAP_AFTER_TURN: int = 1
# Blank lines after each agent turn. Solves "last message glued to
# bottom" (UX-1). Range: 0..3 (CLI_MIN_GAP..CLI_MAX_GAP). Default: 1.

CLI_DEFAULT_ROLE_HEADER_MODE: str = "always"
# Agent role-header visibility. One of "always" | "minimal" | "off".
#   "always"  — full colored bar "🤖 Femtobot ▌" (default).
#   "minimal" — emoji only (legacy Camada 1 behavior).
#   "off"     — no header at all.

CLI_DEFAULT_USER_SEPARATOR: bool = True
# Print a thin "· · ·" divider after each user turn. Default: True.
# Disable for a borderless conversation.

# -- Camada 5 visual separation -------------------------------------------
CLI_DEFAULT_MARGIN_X: int = 2
# Lateral padding (chars) on both sides of agent output. Solves "text
# glued to terminal edges" (P1). Range: 2..4 (CLI_MIN_MARGIN..CLI_MAX_MARGIN).
# Default: 2.

CLI_DEFAULT_GAP_BEFORE_INPUT: int = 0
# Extra blank lines before the "You:" prompt. Solves "last message
# glued to bottom" (P2). Range: 0..4 (CLI_MIN_INPUT_GAP..CLI_MAX_INPUT_GAP).
# Default: 0.

CLI_DEFAULT_TURN_BOX: bool = True
# Render role headers as bracketed boxes "[🤖 Femtobot]" / "[👤 You]"
# so agent and human turns are visually distinct blocks. Solves
# "agent/human indistinguishable" (P3). Default: True.

# -- Bounds (clamped by ``_normalize_*`` helpers in role_renderer) ---------
CLI_MIN_GAP: int = 0
# Inclusive lower bound for ``gap_after_turn``. 0 = no gap.

CLI_MAX_GAP: int = 2
# Inclusive upper bound for ``gap_after_turn``. 2 is the largest number
# of blank lines the renderer will print — beyond that the terminal
# feels empty.

CLI_MIN_MARGIN: int = 2
# Inclusive lower bound for ``margin_x``. 2 = the visual minimum that
# keeps text off the terminal edge. Setting to 0 is not allowed because
# it would defeat P1 ("text glued to terminal edges").

CLI_MAX_MARGIN: int = 4
# Inclusive upper bound for ``margin_x``. 4 chars is the widest
# lateral padding that still leaves room for content on a typical
# 80-col terminal.

CLI_MIN_INPUT_GAP: int = 0
# Inclusive lower bound for ``gap_before_input``. 0 = the prompt sits
# directly under the last reply.

CLI_MAX_INPUT_GAP: int = 4
# Inclusive upper bound for ``gap_before_input``. 4 blank lines is
# enough breathing room without making the user scroll back to
# find context.


class Base(BaseModel):
    """Base model that accepts both camelCase and snake_case keys."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ChannelsConfig(Base):
    """Configuration for chat channels.

    Built-in and plugin channel configs are stored as extra fields (dicts).
    Each channel parses its own config in __init__.
    Per-channel "streaming": true enables streaming output (requires send_delta impl).
    """

    model_config = ConfigDict(extra="allow")

    send_progress: bool = True  # stream agent's text progress to the channel
    send_tool_hints: bool = False  # stream tool-call hints (e.g. read_file("…"))
    show_reasoning: bool = True  # surface model reasoning when channel implements it
    extract_document_text: bool = (
        True  # extract text from document attachments before sending to the model
    )
    send_max_retries: int = Field(
        default=3, ge=0, le=10
    )  # Max delivery attempts (initial send included)
    transcription_provider: str = "groq"  # Voice transcription backend: "groq" or "openai"
    transcription_language: str | None = Field(
        default=None, pattern=r"^[a-z]{2,3}$"
    )  # Optional ISO-639-1 hint for audio transcription


class DreamConfig(Base):
    """Dream memory consolidation configuration."""

    _HOUR_MS = 3_600_000

    enabled: bool = True  # Register the periodic Dream consolidation job on startup
    interval_h: int = Field(default=2, ge=1)  # Every 2 hours by default
    cron: str | None = Field(default=None, exclude=True)  # Legacy cron expression override
    model_override: str | None = Field(
        default=None
    )  # Override model for Dream sessions (pending implementation)
    max_batch_size: int = Field(default=20, ge=1, exclude=True)  # Deprecated: no longer used
    max_iterations: int = Field(default=15, ge=1, exclude=True)  # Deprecated: no longer used
    annotate_line_ages: bool = Field(default=True, exclude=True)  # Deprecated: no longer used

    def describe_schedule(self) -> str:
        """Return a human-readable summary for logs and startup output."""
        if self.cron:
            return f"cron {self.cron} (legacy)"
        hours = self.interval_h
        return f"every {hours}h"


class InlineFallbackConfig(Base):
    """One inline fallback model configuration."""

    model: str
    provider: str
    max_tokens: int | None = None
    context_window_tokens: int | None = None
    temperature: float | None = None
    reasoning_effort: str | None = None


FallbackCandidate = str | InlineFallbackConfig


class ModelPresetConfig(Base):
    """A named set of model + generation parameters for quick switching."""

    label: str | None = None
    model: str
    provider: str = "auto"
    max_tokens: int = 8192
    context_window_tokens: int = 65_536
    temperature: float = 0.1
    reasoning_effort: str | None = None

    def to_generation_settings(self) -> Any:
        from femtobot.providers.base import GenerationSettings

        return GenerationSettings(
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            reasoning_effort=self.reasoning_effort,
        )


class CliWhimsyConfig(Base):
    """Whimsical loading-state verbs and spinner choices for the CLI.

    All fields default to the current Femtobot behavior, so the field is
    fully backward-compatible when this block is added to existing configs.
    """

    verbs_enabled: bool = True
    spinner_style: str = "auto"  # 'auto' | 'dots' | 'dots2' | 'dots3' | 'line' | 'aesthetic'
    verb_pool_size: int = 40


class CliSessionStatusConfig(Base):
    """Lightweight session indicators rendered at end-of-turn and in /status."""

    enabled: bool = True
    show_tokens: bool = True
    show_elapsed: bool = True


class CliBtwConfig(Base):
    """Configuration for the /btw side-question handler."""

    max_history_messages: int = 10
    include_tools_result: bool = False


class CliConfig(Base):
    """CLI behavior configuration.

    All fields default to safe backward-compatible values. See
    FEMTOBOT_CLI_REFACTOR_PLAN.md Camada 1.

    The per-turn spacing knobs (``gap_after_turn``, ``role_header``,
    ``user_separator``, ``margin_x``, ``gap_before_input``, ``turn_box``)
    are documented in detail at the top of this module — look for the
    ``CLI_DEFAULT_*`` and ``CLI_MIN/MAX_*`` block. Override the defaults
    in three ways (highest priority first):
      1. ``/style set margin_x=6 gap_after_turn=2`` (REPL, session-only)
      2. env var — e.g. ``FEMTOBOT_AGENTS__DEFAULTS__CLI__MARGIN_X=6``
      3. ``config.json`` -> ``agents.defaults.cli.*`` (persistent)
    """

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------
    multiline: Literal["off", "backslash"] = "backslash"
    """How multi-line input is collected.

    ``"backslash"`` (default) — a trailing ``\\`` continues the input on
    the next line; pressing Enter on its own submits. Backward-compat
    with the pre-Camada-1 behavior.

    ``"off"`` — every Enter submits a single-line input. Multi-line
    content must be pasted as a single block."""

    completer_enabled: bool = True
    """Enable the tab-completion popup for slash commands, file
    mentions, and command palette suggestions. Disable for a quieter
    REPL on slow terminals."""

    completer_max_results: int = 10
    """Maximum number of completion candidates shown at once. Lower this
    on narrow terminals if the popup overflows."""

    bash_mode_enabled: bool = True
    """Allow the user to invoke a shell command directly by prefixing
    the input with ``!`` (e.g. ``!git status``). Output is captured and
    printed inline; it does NOT enter the agent loop on its own (so
    inspection commands don't burn LLM tokens)."""

    bash_mode_timeout_s: float = 30.0
    """Maximum runtime (seconds) for a ``!bash`` invocation before it's
    killed. Helps prevent runaway commands from blocking the REPL."""

    file_mention_enabled: bool = True
    """When the user types ``@``, suggest files from the active
    workspace so they can be pasted into the prompt as mentions."""

    # ------------------------------------------------------------------
    # Visuals
    # ------------------------------------------------------------------
    theme: str = "terracotta-claude"
    """Name of the active CliTheme (accent colors for the role header,
    status line, and the agent/user turn boxes). Built-in themes:
    ``"terracotta-claude"``. Custom themes live in
    ``femtobot.cli.theme``."""

    whimsy: CliWhimsyConfig = Field(default_factory=CliWhimsyConfig)
    """Whimsical loading-state verbs and spinner style (e.g. "Pondering…",
    "Brewing thoughts…"). See :class:`CliWhimsyConfig`."""

    session_status: CliSessionStatusConfig = Field(default_factory=CliSessionStatusConfig)
    """Lightweight end-of-turn indicators (model, tokens, elapsed). See
    :class:`CliSessionStatusConfig`."""

    btw: CliBtwConfig = Field(default_factory=CliBtwConfig)
    """Configuration for the ``/btw`` side-question handler. See
    :class:`CliBtwConfig`."""

    # ------------------------------------------------------------------
    # Camada 4 — turn-spacing aesthetics (Issue UX-1 / UX-2)
    # ------------------------------------------------------------------
    # These three knobs are the Camada 4 fixes for "messages glued to
    # the bottom of the terminal" (UX-1) and "agent vs human messages
    # look the same" (UX-2). Defaults match the ``CLI_DEFAULT_*``
    # constants at the top of this module.
    gap_after_turn: int = Field(
        default=CLI_DEFAULT_GAP_AFTER_TURN,
        description=(
            "Blank lines printed after each completed agent turn. "
            "Solves UX-1 ('last message glued to bottom'). "
            f"Range: {CLI_MIN_GAP}..{CLI_MAX_GAP}. "
            f"Default: {CLI_DEFAULT_GAP_AFTER_TURN}."
        ),
    )
    """Blank lines printed after each completed agent turn. Range:
    ``CLI_MIN_GAP``..``CLI_MAX_GAP``. Default:
    :data:`CLI_DEFAULT_GAP_AFTER_TURN`."""

    role_header: Literal["always", "minimal", "off"] = Field(
        default=CLI_DEFAULT_ROLE_HEADER_MODE,
        description=(
            "Agent role-header visibility. "
            "'always' = bold colored bar (default), "
            "'minimal' = emoji only, "
            "'off' = no header."
        ),
    )
    """Visibility / style of the agent-side role header. One of
    ``"always"``, ``"minimal"`` or ``"off"``. Default:
    :data:`CLI_DEFAULT_ROLE_HEADER_MODE` (``"always"``)."""

    user_separator: bool = Field(
        default=CLI_DEFAULT_USER_SEPARATOR,
        description=(
            "Print a thin '· · ·' divider after each user turn so the "
            "agent's reply is framed. Disable for a borderless look."
        ),
    )
    """When ``True``, prints a thin dim divider line (``· · · ·``)
    right after the user submits input. Default:
    :data:`CLI_DEFAULT_USER_SEPARATOR` (``True``)."""

    # ------------------------------------------------------------------
    # Camada 5 — visual separation (Issue P1 / P2 / P3)
    # ------------------------------------------------------------------
    # These three knobs are the Camada 5 fixes for "text glued to
    # terminal edges" (P1), "last message glued to bottom" (P2), and
    # "agent/human messages indistinguishable" (P3).
    margin_x: int = Field(
        default=CLI_DEFAULT_MARGIN_X,
        description=(
            "Lateral padding (chars) on both sides of agent output via "
            "rich.Padding. Solves P1 ('text glued to terminal edges'). "
            f"Range: {CLI_MIN_MARGIN}..{CLI_MAX_MARGIN}. "
            f"Default: {CLI_DEFAULT_MARGIN_X}."
        ),
    )
    """Lateral padding (chars) on both sides of agent output. Range:
    ``CLI_MIN_MARGIN``..``CLI_MAX_MARGIN``. Default:
    :data:`CLI_DEFAULT_MARGIN_X`."""

    gap_before_input: int = Field(
        default=CLI_DEFAULT_GAP_BEFORE_INPUT,
        description=(
            "Extra blank lines printed before the 'You:' prompt. "
            "Solves P2 ('last message glued to bottom'). "
            f"Range: {CLI_MIN_INPUT_GAP}..{CLI_MAX_INPUT_GAP}. "
            f"Default: {CLI_DEFAULT_GAP_BEFORE_INPUT}."
        ),
    )
    """Extra blank lines printed before the ``You:`` prompt. Range:
    ``CLI_MIN_INPUT_GAP``..``CLI_MAX_INPUT_GAP``. Default:
    :data:`CLI_DEFAULT_GAP_BEFORE_INPUT`."""

    turn_box: bool = Field(
        default=CLI_DEFAULT_TURN_BOX,
        description=(
            "Render role headers as bracketed boxes '[🤖 Femtobot]' / "
            "'[👤 You]'. Solves P3 ('agent/human indistinguishable'). "
            "Set to false to revert to the legacy bar + plain 'You:'."
        ),
    )
    """When ``True``, render role headers as bracketed boxes
    (``[🤖 Femtobot]`` for the agent, ``[👤 You]`` for the user).
    Default: :data:`CLI_DEFAULT_TURN_BOX` (``True``)."""


class AgentDefaults(Base):
    """Default agent configuration."""

    workspace: str = "~/.femtobot/workspace"
    model_preset: str | None = None  # Active preset name — takes precedence over fields below
    model: str = "anthropic/claude-opus-4-5"
    provider: str = (
        "auto"  # Provider name (e.g. "anthropic", "openrouter") or "auto" for auto-detection
    )
    max_tokens: int = 8192
    context_window_tokens: int = 65_536
    context_block_limit: int | None = None
    temperature: float = 0.1
    fallback_models: list[FallbackCandidate] = Field(default_factory=list)
    max_tool_iterations: int = 200
    max_concurrent_subagents: int = Field(default=1, ge=1)
    max_tool_result_chars: int = 16_000
    provider_retry_mode: Literal["standard", "persistent"] = "standard"
    tool_hint_max_length: int = Field(
        default=40,
        ge=20,
        le=500,
    )  # Max characters for tool hint display (e.g. "$ cd …/project && npm test")
    reasoning_effort: str | None = (
        None  # low / medium / high / adaptive / none — LLM thinking effort; None preserves the provider default
    )
    timezone: str = "UTC"  # IANA timezone, e.g. "Asia/Shanghai", "America/New_York"
    bot_name: str = "Femtobot"  # Display name shown in CLI prompts (e.g. "{name} is thinking...")
    bot_icon: str = "🐈"  # Short icon (emoji or text) shown next to the bot name in CLI; "" to omit
    unified_session: bool = (
        False  # Share one session across all channels (single-user multi-device)
    )
    disabled_skills: list[str] = Field(
        default_factory=list
    )  # Skill names to exclude from loading (e.g. ["summarize", "skill-creator"])
    session_ttl_minutes: int = Field(
        default=0,
        ge=0,
    )  # Auto-compact idle threshold in minutes (0 = disabled)
    max_messages: int = Field(
        default=120,
        ge=0,
    )  # Max messages to replay from session history (0 = use default 120, respects token budget)
    consolidation_ratio: float = Field(
        default=0.5,
        ge=0.1,
        le=0.95,
    )  # Consolidation target ratio (0.5 = 50% of budget retained after compression)
    dream: DreamConfig = Field(default_factory=DreamConfig)
    notify_mcp_startup_failures: bool = (
        False  # When True, surface MCP startup failures to the user (Fase 6)
    )
    include_mcp_context: bool = (
        False  # When True, read AGENTS.md/MEMORY.md headers from MCPs (Fase 8)
    )
    cli: CliConfig = Field(default_factory=CliConfig)  # Camada 1 CLI behavior


class AgentsConfig(Base):
    """Agent configuration."""

    defaults: AgentDefaults = Field(default_factory=AgentDefaults)


class ProviderConfig(Base):
    """LLM provider configuration."""

    api_key: str | None = None
    api_base: str | None = None
    api_type: Literal["auto", "chat_completions", "responses"] = "auto"  # Request API surface
    extra_headers: dict[str, str] | None = None  # Custom headers (e.g. APP-Code for AiHubMix)
    extra_body: dict[str, Any] | None = (
        None  # Extra provider request fields; shape depends on provider/API surface
    )
    # A11 (REFACTOR_PLAN.md Lote A): per-request query string.  Some
    # regional providers (e.g. Azure-style ?api-version=, certain
    # gateways) require a query string that ``extra_headers`` /
    # ``extra_body`` cannot model.  Values must be strings; bools and
    # numbers get coerced via ``str()`` to keep the wire format simple.
    extra_query: dict[str, str] | None = None
    # D1 (REFACTOR_PLAN.md Lote D): AWS Bedrock region override.  When
    # set, takes precedence over ``BEDROCK_REGION`` / ``AWS_REGION`` /
    # the ``us-east-1`` default.  Other providers ignore this field.
    region: str | None = None


class ProvidersConfig(Base):
    """Configuration for LLM providers."""

    custom: ProviderConfig = Field(default_factory=ProviderConfig)  # Any OpenAI-compatible endpoint
    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)
    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    openrouter: ProviderConfig = Field(default_factory=ProviderConfig)
    huggingface: ProviderConfig = Field(default_factory=ProviderConfig)
    skywork: ProviderConfig = Field(default_factory=ProviderConfig)  # Skywork / APIFree API gateway
    deepseek: ProviderConfig = Field(default_factory=ProviderConfig)
    groq: ProviderConfig = Field(default_factory=ProviderConfig)
    zhipu: ProviderConfig = Field(default_factory=ProviderConfig)
    dashscope: ProviderConfig = Field(default_factory=ProviderConfig)
    vllm: ProviderConfig = Field(default_factory=ProviderConfig)
    ollama: ProviderConfig = Field(default_factory=ProviderConfig)  # Ollama local models
    lm_studio: ProviderConfig = Field(default_factory=ProviderConfig)  # LM Studio local models
    atomic_chat: ProviderConfig = Field(default_factory=ProviderConfig)  # Atomic Chat local models
    ovms: ProviderConfig = Field(default_factory=ProviderConfig)  # OpenVINO Model Server (OVMS)
    gemini: ProviderConfig = Field(default_factory=ProviderConfig)
    moonshot: ProviderConfig = Field(default_factory=ProviderConfig)
    minimax: ProviderConfig = Field(default_factory=ProviderConfig)
    minimax_anthropic: ProviderConfig = Field(
        default_factory=ProviderConfig
    )  # MiniMax Anthropic endpoint (thinking)
    mistral: ProviderConfig = Field(default_factory=ProviderConfig)
    stepfun: ProviderConfig = Field(default_factory=ProviderConfig)  # Step Fun (阶跃星辰)
    xiaomi_mimo: ProviderConfig = Field(default_factory=ProviderConfig)  # Xiaomi MIMO (小米)
    longcat: ProviderConfig = Field(default_factory=ProviderConfig)  # LongCat
    ant_ling: ProviderConfig = Field(default_factory=ProviderConfig)  # Ant Ling
    aihubmix: ProviderConfig = Field(default_factory=ProviderConfig)  # AiHubMix API gateway
    siliconflow: ProviderConfig = Field(default_factory=ProviderConfig)  # SiliconFlow (硅基流动)
    novita: ProviderConfig = Field(default_factory=ProviderConfig)  # Novita AI
    volcengine: ProviderConfig = Field(default_factory=ProviderConfig)  # VolcEngine (火山引擎)
    volcengine_coding_plan: ProviderConfig = Field(
        default_factory=ProviderConfig
    )  # VolcEngine Coding Plan
    byteplus: ProviderConfig = Field(
        default_factory=ProviderConfig
    )  # BytePlus (VolcEngine international)
    byteplus_coding_plan: ProviderConfig = Field(
        default_factory=ProviderConfig
    )  # BytePlus Coding Plan

    qianfan: ProviderConfig = Field(default_factory=ProviderConfig)  # Qianfan (百度千帆)
    nvidia: ProviderConfig = Field(default_factory=ProviderConfig)  # NVIDIA NIM (nvapi- keys)
    # D1 (REFACTOR_PLAN.md Lote D): AWS Bedrock (Converse API).  Auth
    # via ``AWS_*`` env vars or ``BEDROCK_API_KEY`` (treated as the
    # session token).  ``region`` overrides ``BEDROCK_REGION``.
    bedrock: ProviderConfig = Field(default_factory=ProviderConfig)

    @model_validator(mode="after")
    def _validate_api_type_scope(self) -> "ProvidersConfig":
        for name in self.__class__.model_fields:
            if name == "openai":
                continue
            provider = getattr(self, name, None)
            if isinstance(provider, ProviderConfig) and provider.api_type != "auto":
                raise ValueError("providers.<name>.api_type is only supported for providers.openai")
        return self


class HeartbeatConfig(Base):
    """Heartbeat service configuration (now backed by cron)."""

    enabled: bool = True
    interval_s: int = 30 * 60  # 30 minutes
    keep_recent_messages: int = 8


class ApiConfig(Base):
    """OpenAI-compatible API server configuration."""

    host: str = "127.0.0.1"  # Safer default: local-only bind.
    port: int = 8900
    timeout: float = 120.0  # Per-request timeout in seconds.


class GatewayConfig(Base):
    """Gateway/server configuration."""

    host: str = "127.0.0.1"  # Safer default: local-only bind.
    port: int = 18790
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)


class MCPServerConfig(Base):
    """MCP server connection configuration (stdio or HTTP)."""

    type: Literal["stdio", "sse", "streamableHttp"] | None = None  # auto-detected if omitted
    command: str = ""  # Stdio: command to run (e.g. "npx")
    args: list[str] = Field(default_factory=list)  # Stdio: command arguments
    env: dict[str, str] = Field(default_factory=dict)  # Stdio: extra env vars
    cwd: str = ""  # Stdio: working directory for MCP server runtime artifacts
    url: str = ""  # HTTP/SSE: endpoint URL
    headers: dict[str, str] = Field(default_factory=dict)  # HTTP/SSE: custom headers
    tool_timeout: int = 30  # seconds before a tool call is cancelled
    enabled_tools: list[str] = Field(
        default_factory=lambda: ["*"]
    )  # Only register these tools; accepts raw MCP names or wrapped mcp_<server>_<tool> names; ["*"] = all tools; [] = no tools
    # C4 (REFACTOR_PLAN.md Lote C): tags / capabilities surfaced to the
    # system prompt for tools backed by this MCP server.  Common values:
    # ``long-running``, ``needs-confirmation``, ``stateful``, ``network``.
    # Each tool is registered with these capabilities appended to its
    # own ``capabilities`` list.
    capability_mentions: list[str] = Field(default_factory=list)


def _lazy_default(module_path: str, class_name: str) -> Any:
    """Deferred import helper for ToolsConfig default factories."""
    import importlib

    module = importlib.import_module(module_path)
    return getattr(module, class_name)()


class ToolsConfig(Base):
    """Tools configuration.

    Field types for tool-specific sub-configs are resolved via model_rebuild()
    at the bottom of this file to avoid circular imports (tool modules import
    Base from schema.py).
    """

    web: WebToolsConfig = Field(
        default_factory=lambda: _lazy_default("femtobot.agent.tools.web", "WebToolsConfig")
    )
    exec: ExecToolConfig = Field(
        default_factory=lambda: _lazy_default("femtobot.agent.tools.shell", "ExecToolConfig")
    )
    my: MyToolConfig = Field(
        default_factory=lambda: _lazy_default("femtobot.agent.tools.self", "MyToolConfig")
    )
    restrict_to_workspace: bool = (
        False  # policy intent: keep tool access inside workspace when possible
    )
    webui_allow_local_service_access: bool = Field(default=True)
    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)
    ssrf_whitelist: list[str] = Field(
        default_factory=list
    )  # CIDR ranges to exempt from SSRF blocking (e.g. ["100.64.0.0/10"] for Tailscale)


class Config(BaseSettings):
    """Root configuration for femtobot."""

    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    model_presets: dict[str, ModelPresetConfig] = Field(default_factory=dict)

    def __init__(self, **values: Any) -> None:
        if not type(self).__pydantic_complete__:
            _resolve_tool_config_refs()
        super().__init__(**values)

    @model_validator(mode="after")
    def _validate_model_preset(self) -> "Config":
        if "default" in self.model_presets:
            raise ValueError("model_preset name 'default' is reserved for agents.defaults")
        name = self.agents.defaults.model_preset
        if name and name != "default" and name not in self.model_presets:
            raise ValueError(f"model_preset {name!r} not found in model_presets")
        for fallback in self.agents.defaults.fallback_models:
            if isinstance(fallback, str) and fallback not in self.model_presets:
                raise ValueError(f"fallback_models entry {fallback!r} not found in model_presets")
        return self

    def resolve_default_preset(self) -> ModelPresetConfig:
        """Return the implicit `default` preset from agents.defaults fields."""
        d = self.agents.defaults
        return ModelPresetConfig(
            model=d.model,
            provider=d.provider,
            max_tokens=d.max_tokens,
            context_window_tokens=d.context_window_tokens,
            temperature=d.temperature,
            reasoning_effort=d.reasoning_effort,
        )

    def resolve_preset(self, name: str | None = None) -> ModelPresetConfig:
        """Return effective model params from a named preset or the implicit default."""
        name = self.agents.defaults.model_preset if name is None else name
        if not name or name == "default":
            return self.resolve_default_preset()
        if name not in self.model_presets:
            raise KeyError(f"model_preset {name!r} not found in model_presets")
        return self.model_presets[name]

    @property
    def workspace_path(self) -> Path:
        """Get expanded workspace path, resolved relative to instance_dir.

        Delegates to ``femtobot.config.paths.get_workspace_path`` so the
        workspace is always resolved relative to the active instance
        directory, never the process CWD.
        """
        from femtobot.config.paths import get_workspace_path

        return get_workspace_path(self.agents.defaults.workspace)

    def _match_provider(
        self,
        model: str | None = None,
        *,
        preset: ModelPresetConfig | None = None,
    ) -> tuple["ProviderConfig | None", str | None]:
        """Match provider config and its registry name. Returns (config, spec_name)."""
        from femtobot.providers.registry import PROVIDERS, find_by_name

        resolved = preset or self.resolve_preset()
        forced = resolved.provider
        if forced != "auto":
            spec = find_by_name(forced)
            if spec:
                p = getattr(self.providers, spec.name, None)
                return (p, spec.name) if p else (None, None)
            return None, None

        model_lower = (model or resolved.model).lower()
        model_normalized = model_lower.replace("-", "_")
        model_prefix = model_lower.split("/", 1)[0] if "/" in model_lower else ""
        normalized_prefix = model_prefix.replace("-", "_")

        def _kw_matches(kw: str) -> bool:
            kw = kw.lower()
            return kw in model_lower or kw.replace("-", "_") in model_normalized

        # Explicit provider prefix wins — prevents `github-copilot/...codex` matching openai_codex.
        for spec in PROVIDERS:
            p = getattr(self.providers, spec.name, None)
            if p and model_prefix and normalized_prefix == spec.name:
                if spec.is_oauth or spec.is_local or spec.is_direct or p.api_key:
                    return p, spec.name

        # Match by keyword (order follows PROVIDERS registry)
        for spec in PROVIDERS:
            p = getattr(self.providers, spec.name, None)
            if p and any(_kw_matches(kw) for kw in spec.keywords):
                if spec.is_oauth or spec.is_local or spec.is_direct or p.api_key:
                    return p, spec.name

        # Fallback: configured local providers can route models without
        # provider-specific keywords (for example plain "llama3.2" on Ollama).
        # Prefer providers whose detect_by_base_keyword matches the configured api_base
        # (e.g. Ollama's "11434" in "http://localhost:11434") over plain registry order.
        local_fallback: tuple[ProviderConfig, str] | None = None
        for spec in PROVIDERS:
            if not spec.is_local:
                continue
            p = getattr(self.providers, spec.name, None)
            if not (p and p.api_base):
                continue
            if spec.detect_by_base_keyword and spec.detect_by_base_keyword in p.api_base:
                return p, spec.name
            if local_fallback is None:
                local_fallback = (p, spec.name)
        if local_fallback:
            return local_fallback

        # Fallback: gateways first, then others (follows registry order)
        # OAuth providers are NOT valid fallbacks — they require explicit model selection
        for spec in PROVIDERS:
            if spec.is_oauth:
                continue
            p = getattr(self.providers, spec.name, None)
            if p and p.api_key:
                return p, spec.name
        return None, None

    def get_provider(
        self,
        model: str | None = None,
        *,
        preset: ModelPresetConfig | None = None,
    ) -> ProviderConfig | None:
        """Get matched provider config (api_key, api_base, extra_headers). Falls back to first available."""
        p, _ = self._match_provider(model, preset=preset)
        return p

    def get_provider_name(
        self,
        model: str | None = None,
        *,
        preset: ModelPresetConfig | None = None,
    ) -> str | None:
        """Get the registry name of the matched provider (e.g. "deepseek", "openrouter")."""
        _, name = self._match_provider(model, preset=preset)
        return name

    def get_api_key(
        self,
        model: str | None = None,
        *,
        preset: ModelPresetConfig | None = None,
    ) -> str | None:
        """Get API key for the given model. Falls back to first available key."""
        p = self.get_provider(model, preset=preset)
        return p.api_key if p else None

    def get_api_base(
        self,
        model: str | None = None,
        *,
        preset: ModelPresetConfig | None = None,
    ) -> str | None:
        """Get API base URL for the given model, falling back to the provider default when present."""
        from femtobot.providers.registry import find_by_name

        p, name = self._match_provider(model, preset=preset)
        if p and p.api_base:
            return p.api_base
        if name:
            spec = find_by_name(name)
            if spec and spec.default_api_base:
                return spec.default_api_base
        return None

    model_config = ConfigDict(env_prefix="FEMTOBOT_", env_nested_delimiter="__")


def _resolve_tool_config_refs() -> None:
    """Resolve forward references in ToolsConfig by importing tool config classes.

    Must be called after all modules are loaded (breaks circular imports).
    Re-exports the classes into this module's namespace so existing imports
    like ``from femtobot.config.schema import ExecToolConfig`` continue to work.
    """
    import sys

    from femtobot.agent.tools.self import MyToolConfig
    from femtobot.agent.tools.shell import ExecToolConfig
    from femtobot.agent.tools.web import WebFetchConfig, WebSearchConfig, WebToolsConfig

    # Re-export into this module's namespace
    mod = sys.modules[__name__]
    mod.ExecToolConfig = ExecToolConfig  # type: ignore[attr-defined]
    mod.WebToolsConfig = WebToolsConfig  # type: ignore[attr-defined]
    mod.WebSearchConfig = WebSearchConfig  # type: ignore[attr-defined]
    mod.WebFetchConfig = WebFetchConfig  # type: ignore[attr-defined]
    mod.MyToolConfig = MyToolConfig  # type: ignore[attr-defined]

    ToolsConfig.model_rebuild()
    Config.model_rebuild()


# Eagerly resolve when the import chain allows it (no circular deps at this
# point).  If it fails (first import triggers a cycle), the rebuild will
# happen lazily when Config/ToolsConfig is first used at runtime.
try:
    _resolve_tool_config_refs()
except ImportError:
    pass
