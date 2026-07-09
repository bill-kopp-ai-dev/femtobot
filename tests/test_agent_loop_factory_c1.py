"""C1: ``AgentLoop.from_config`` is the canonical factory (C1).

C1 (REFACTOR_PLAN.md Lote C): ``AgentLoop.from_config`` is the entry
point for embedders that don't need the ``Femtobot`` facade.  We pin
its signature here so a future refactor doesn't accidentally drop a
keyword-only argument.
"""

from __future__ import annotations

import inspect

import pytest

from femtobot.agent.loop import AgentLoop

pytestmark = pytest.mark.architecture


def test_from_config_is_classmethod() -> None:
    """C1: ``from_config`` is a classmethod (C1)."""
    assert inspect.ismethod(AgentLoop.from_config)


def test_from_config_signature() -> None:
    """C1: ``from_config(config, bus=None, **extra)`` is the public signature (C1)."""
    sig = inspect.signature(AgentLoop.from_config)
    params = list(sig.parameters.values())
    # First param may be ``cls`` (unbound) or ``config`` (bound); check
    # both shapes defensively.
    assert params[0].name in ("cls", "config")
    config_idx = next(
        i for i, p in enumerate(params) if p.name == "config"
    )
    assert config_idx == 0 or params[config_idx - 1].name == "cls"
    assert params[config_idx].default is inspect.Parameter.empty
    # ``bus`` is a keyword arg with default ``None``.
    bus_idx = next(i for i, p in enumerate(params) if p.name == "bus")
    assert params[bus_idx].default is None
    # ``**extra`` must be present so callers can override init args.
    assert any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params)


def test_from_config_docstring_mentions_c1() -> None:
    """C1: the docstring references the Lote C item (C1)."""
    doc = AgentLoop.from_config.__doc__ or ""
    assert "C1" in doc or "REFACTOR_PLAN" in doc


def test_femtobot_from_config_delegates_to_agent_loop() -> None:
    """C1: ``Femtobot.from_config`` calls ``AgentLoop.from_config`` (C1)."""
    from femtobot.femtobot import Femtobot

    src = inspect.getsource(Femtobot.from_config)
    assert "AgentLoop.from_config" in src
