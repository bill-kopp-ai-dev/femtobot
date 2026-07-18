"""Tests for the Femtobot 1.0 PydanticAI adapter (Phase 1).

These tests exercise the new FemtobotAgent factory, FemtobotDeps,
FemtobotOutput validators, and the femtobot_timer toolset pilot —
without touching the legacy AgentLoop.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from femtobot.agent.deps import FemtobotDeps
from femtobot.agent.femtobot_agent import FemtobotAgent
from femtobot.agent.output import FemtobotOutput
from femtobot.agent.toolsets.femtobot_timer import (
    _impl,
    femtobot_timer,
    toolset,
)
from femtobot.config.schema import Config


# ---------------------------------------------------------------------------
# FemtobotDeps
# ---------------------------------------------------------------------------


def _make_config() -> Config:
    """Return a Config with sane defaults for tests."""
    return Config()


def test_femtobot_deps_defaults() -> None:
    cfg = _make_config()
    deps = FemtobotDeps(config=cfg, workspace=Path("/tmp"))
    assert deps.config is cfg
    assert deps.workspace == Path("/tmp")
    assert deps.session is None
    assert deps.session_manager is None
    assert deps.skills is None
    assert deps.workspace_scope is None
    assert deps.run_metadata == {}


def test_femtobot_deps_slots() -> None:
    """The dataclass uses slots=True (perf + immutability)."""
    deps = FemtobotDeps(config=_make_config(), workspace=Path("/tmp"))
    with pytest.raises(AttributeError):
        deps.bogus_field = "x"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# FemtobotOutput validators
# ---------------------------------------------------------------------------


def test_femtobot_output_rejects_empty_message() -> None:
    with pytest.raises(ValidationError):
        FemtobotOutput(final_message="")


def test_femtobot_output_rejects_whitespace_only_message() -> None:
    with pytest.raises(ValidationError):
        FemtobotOutput(final_message="   \n\t  ")


def test_femtobot_output_rejects_internal_file_references() -> None:
    for forbidden in ("AGENTS.md", "SOUL.md", "HEARTBEAT.md", "AWARENESS.md"):
        # Path-like references (preceded by '/' or './') are blocked.
        with pytest.raises(ValidationError):
            FemtobotOutput(final_message=f"see ./workspace/{forbidden}")
        with pytest.raises(ValidationError):
            FemtobotOutput(final_message=f"see /home/user/.femtobot/{forbidden}")


def test_femtobot_output_accepts_normal_message() -> None:
    out = FemtobotOutput(
        final_message="Hello, world.",
        iterations_used=3,
        completed_goal=True,
    )
    assert out.final_message == "Hello, world."
    assert out.iterations_used == 3
    assert out.completed_goal is True


def test_femtobot_output_defaults() -> None:
    out = FemtobotOutput(final_message="ok")
    assert out.iterations_used == 0
    assert out.completed_goal is False


# ---------------------------------------------------------------------------
# femtobot_timer toolset
# ---------------------------------------------------------------------------


def test_toolset_returns_one_tool() -> None:
    ts = toolset()
    assert len(ts) == 1
    assert ts[0].name == "femtobot_timer"
    assert ts[0].takes_ctx is True


def test_impl_now_returns_utc_and_local() -> None:
    cfg = _make_config()
    cfg.agents.defaults.timezone = "UTC"
    deps = FemtobotDeps(config=cfg, workspace=Path("/tmp"))
    result = _impl("now", deps)
    assert "User-local:" in result
    assert "UTC:" in result


def test_impl_utc_returns_iso() -> None:
    cfg = _make_config()
    deps = FemtobotDeps(config=cfg, workspace=Path("/tmp"))
    result = _impl("utc", deps)
    # ISO-8601 has at least one 'T' separator
    assert "T" in result


def test_impl_user_local_returns_iso() -> None:
    cfg = _make_config()
    cfg.agents.defaults.timezone = "UTC"
    deps = FemtobotDeps(config=cfg, workspace=Path("/tmp"))
    result = _impl("user_local", deps)
    assert "T" in result


def test_impl_calendar_returns_block() -> None:
    cfg = _make_config()
    cfg.agents.defaults.timezone = "UTC"
    deps = FemtobotDeps(config=cfg, workspace=Path("/tmp"))
    result = _impl("calendar", deps)
    assert "Timezone:" in result
    assert "Weekday:" in result


def test_impl_iso_date_returns_weekday() -> None:
    cfg = _make_config()
    deps = FemtobotDeps(config=cfg, workspace=Path("/tmp"))
    result = _impl("2026-07-18", deps)
    assert "week" in result.lower()
    assert "2026-07-18" in result


def test_impl_unrecognized_returns_helpful_message() -> None:
    cfg = _make_config()
    deps = FemtobotDeps(config=cfg, workspace=Path("/tmp"))
    result = _impl("not-a-date", deps)
    assert "Unrecognized query" in result


def test_impl_invalid_timezone_falls_back_to_utc() -> None:
    cfg = _make_config()
    cfg.agents.defaults.timezone = "Not/A/Real/Zone"
    deps = FemtobotDeps(config=cfg, workspace=Path("/tmp"))
    result = _impl("calendar", deps)
    assert "Warning" in result
    assert "UTC" in result


@pytest.mark.asyncio
async def test_femtobot_timer_function_calls_impl() -> None:
    cfg = _make_config()
    cfg.agents.defaults.timezone = "UTC"
    deps = FemtobotDeps(config=cfg, workspace=Path("/tmp"))

    class _Ctx:
        pass

    # RunContext-like duck-type: PydanticAI only reads .deps
    ctx = _Ctx()
    ctx.deps = deps  # type: ignore[attr-defined]
    result = await femtobot_timer(ctx, query="utc")  # type: ignore[arg-type]
    assert "T" in result


# ---------------------------------------------------------------------------
# FemtobotAgent factory (no network)
# ---------------------------------------------------------------------------


def test_femtobot_agent_lazy_construction() -> None:
    """FemtobotAgent must not touch the model until .agent is accessed."""
    cfg = _make_config()
    agent = FemtobotAgent(cfg, Path("/tmp"))
    # No API key set — the agent should still construct without error
    # because _build_model is only called inside the .agent property.
    assert agent._agent is None


def test_femtobot_agent_rebuild_resets() -> None:
    cfg = _make_config()
    agent = FemtobotAgent(cfg, Path("/tmp"), tools=toolset())
    # Force-set the cached agent to a sentinel
    agent._agent = MagicMock()
    agent.rebuild()
    assert agent._agent is None


def test_femtobot_agent_with_tools() -> None:
    cfg = _make_config()
    agent = FemtobotAgent(cfg, Path("/tmp"), tools=toolset())
    assert len(agent._tools) == 1
    assert agent._tools[0].name == "femtobot_timer"


# ---------------------------------------------------------------------------
# FemtobotAgent.from_config / combined_toolset (Phase 3)
# ---------------------------------------------------------------------------


def test_femtobot_agent_from_config_classmethod() -> None:
    """``from_config`` is the canonical Phase 4 constructor shape."""
    from femtobot.agent.femtobot_agent import FemtobotAgent

    cfg = _make_config()
    agent = FemtobotAgent.from_config(cfg, Path("/tmp"), tools=toolset())
    assert agent._config is cfg
    assert agent._workspace == Path("/tmp")
    assert len(agent._tools) == 1


def test_femtobot_agent_use_combined_toolset() -> None:
    """``use_combined_toolset=True`` pulls every migrated toolset."""
    from femtobot.agent.femtobot_agent import FemtobotAgent

    cfg = _make_config()
    agent = FemtobotAgent(cfg, Path("/tmp"), use_combined_toolset=True)
    # femtobot_timer is the only migrated toolset so far.
    assert len(agent._tools) >= 1
    assert any(t.name == "femtobot_timer" for t in agent._tools)


def test_combined_toolset_returns_migrated_tools() -> None:
    """``combined_toolset`` aggregates every toolset module under toolsets/."""
    from femtobot.agent.toolsets._combined import combined_toolset

    tools = combined_toolset()
    names = [t.name for t in tools]
    assert "femtobot_timer" in names


# ---------------------------------------------------------------------------
# Provider dispatch (Phase 5)
# ---------------------------------------------------------------------------


def test_build_model_openai_with_provider_kwargs() -> None:
    """OpenAI provider picks up api_key and api_base from config."""
    from pydantic_ai.models.openai import OpenAIModel

    from femtobot.agent.femtobot_agent import _build_model

    cfg = _make_config()
    cfg.agents.defaults.provider = "openai"
    cfg.agents.defaults.model = "gpt-4o-mini"
    cfg.providers.openai.api_key = "sk-test"
    cfg.providers.openai.api_base = "https://api.example.com/v1"

    model = _build_model(cfg)
    assert isinstance(model, OpenAIModel)


def test_build_model_openai_compat_uses_base_url() -> None:
    """Regional OpenAI-compat providers (e.g. dashscope) get the custom base_url."""
    from pydantic_ai.models.openai import OpenAIModel

    from femtobot.agent.femtobot_agent import _build_model

    cfg = _make_config()
    cfg.agents.defaults.provider = "dashscope"
    cfg.agents.defaults.model = "qwen-max"
    cfg.providers.dashscope.api_key = "sk-test"
    cfg.providers.dashscope.api_base = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    model = _build_model(cfg)
    assert isinstance(model, OpenAIModel)


def test_build_model_anthropic_without_sdk_raises_helpful_error() -> None:
    """When anthropic SDK is not installed, we get a clean RuntimeError."""
    from femtobot.agent.femtobot_agent import _build_model

    cfg = _make_config()
    cfg.agents.defaults.provider = "anthropic"
    cfg.agents.defaults.model = "claude-3-5-sonnet"
    cfg.providers.anthropic.api_key = "sk-ant-test"

    # The anthropic SDK may or may not be installed in this environment.
    # Either path is acceptable: success returns an AnthropicModel,
    # failure raises RuntimeError with an actionable message.
    try:
        model = _build_model(cfg)
        from pydantic_ai.models.anthropic import AnthropicModel

        assert isinstance(model, AnthropicModel)
    except RuntimeError as exc:
        assert "anthropic" in str(exc).lower()


def test_build_model_bedrock_without_sdk_raises_helpful_error() -> None:
    """When boto3 is not installed, we get a clean RuntimeError."""
    from femtobot.agent.femtobot_agent import _build_model

    cfg = _make_config()
    cfg.agents.defaults.provider = "bedrock"
    cfg.agents.defaults.model = "anthropic.claude-3-5-sonnet"
    cfg.providers.bedrock.api_key = "aws-test"

    try:
        model = _build_model(cfg)
        from pydantic_ai.models.bedrock import BedrockConverseModel

        assert isinstance(model, BedrockConverseModel)
    except RuntimeError as exc:
        assert "boto3" in str(exc).lower() or "bedrock" in str(exc).lower()


def test_build_model_gemini_without_sdk_raises_helpful_error() -> None:
    """When google-genai is not installed, we get a clean RuntimeError."""
    from femtobot.agent.femtobot_agent import _build_model

    cfg = _make_config()
    cfg.agents.defaults.provider = "gemini"
    cfg.agents.defaults.model = "gemini-1.5-pro"
    cfg.providers.gemini.api_key = "gemini-test"

    try:
        model = _build_model(cfg)
        # Accept either the new GoogleModel or the deprecated GeminiModel alias.
        try:
            from pydantic_ai.models.google import GoogleModel

            assert isinstance(model, GoogleModel)
        except ImportError:
            from pydantic_ai.models.gemini import GeminiModel  # type: ignore[no-redef]

            assert isinstance(model, GeminiModel)
    except RuntimeError as exc:
        assert "gemini" in str(exc).lower() or "google" in str(exc).lower()


def test_build_model_unknown_provider_raises_value_error() -> None:
    """An unknown provider name raises a clear ValueError."""
    from femtobot.agent.femtobot_agent import _build_model

    cfg = _make_config()
    cfg.agents.defaults.provider = "definitely_not_a_provider"
    with pytest.raises(ValueError, match="Unknown provider"):
        _build_model(cfg)
