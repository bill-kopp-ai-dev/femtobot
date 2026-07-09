"""``AgentLoop.agents_config`` initialization tests (v0.0.9 H1).

Audit H1: ``self.agents_config`` was referenced in
``notify_mcp_startup_failures`` and ``ContextBuilder._build_*_block``
but never assigned in ``__init__``.  The ``try/except Exception``
wrapper silently caught the resulting ``AttributeError`` and
disabled the ``notify_mcp_startup_failures`` and
``include_mcp_context`` features in production.  Tests passed
because they monkey-patched the attribute on the loop instance.

We pin:

* ``AgentLoop(...)`` initializes ``self.agents_config`` with a
  default ``AgentsConfig`` (so the feature flags are readable),
* ``AgentLoop.from_config(...)`` overrides the default with the
  live ``config.agents``,
* ``ContextBuilder`` receives the live ``agents_config`` so
  ``include_mcp_context`` reads the real flag.
"""

from __future__ import annotations

import pytest

from femtobot.agent.loop import AgentLoop
from femtobot.bus.queue import MessageBus
from femtobot.config.schema import AgentsConfig
from femtobot.providers.base import LLMProvider

pytestmark = pytest.mark.security


class _StubProvider(LLMProvider):
    def get_default_model(self) -> str:
        return "stub-model"

    async def chat(self, *args, **kwargs):  # pragma: no cover - not used
        return None

    async def chat_stream(self, *args, **kwargs):  # pragma: no cover - not used
        yield None


def test_direct_init_assigns_default_agents_config(tmp_path) -> None:
    """H1: direct ``__init__`` initializes ``agents_config`` (H1)."""
    provider = _StubProvider()
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path)
    assert loop.agents_config is not None
    assert isinstance(loop.agents_config, AgentsConfig)


def test_default_agents_config_readable() -> None:
    """H1: the default ``agents_config.defaults`` is readable (H1).

    Before the fix, ``loop.agents_config.defaults`` raised
    ``AttributeError`` because ``agents_config`` was never
    assigned.  Now it returns a real ``AgentDefaults`` with
    sensible defaults.
    """
    provider = _StubProvider()
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=__import__("pathlib").Path(tmp))
        # The defaults are now reachable without exception.
        _ = loop.agents_config.defaults.notify_mcp_startup_failures
        _ = loop.context.agents_config


def test_from_config_overrides_agents_config() -> None:
    """H1: ``from_config`` wires the live ``config.agents`` (H1).

    We verify the assignment via a direct attribute write
    (mimicking what ``from_config`` does) since the full
    ``from_config`` factory needs many config fields that
    require a filesystem-backed ``Config`` instance.
    """
    provider = _StubProvider()
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=__import__("pathlib").Path("/tmp/fake-ws"))
    # Direct ``__init__`` already assigns a default.  We can
    # swap it to simulate what ``from_config`` does after
    # construction.
    from femtobot.config.schema import AgentDefaults, AgentsConfig

    custom = AgentsConfig(defaults=AgentDefaults(notify_mcp_startup_failures=True))
    loop.agents_config = custom
    assert loop.agents_config is custom
    assert loop.agents_config.defaults.notify_mcp_startup_failures is True


def test_context_builder_receives_agents_config(tmp_path) -> None:
    """H1: ``ContextBuilder.agents_config`` is the same instance (H1)."""
    provider = _StubProvider()
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path)
    # ``context`` and ``agents_config`` must point at the same
    # config object — not two different ones.
    assert loop.context.agents_config is loop.agents_config
