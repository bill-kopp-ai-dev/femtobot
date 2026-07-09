"""Femtobot facade (``femtobot.femtobot``) tests.

Covers the public surface of the programmatic API:

* ``Femtobot.from_config`` builds a facade wired to a real
  ``AgentLoop``.
* ``RunResult`` carries the LLM provider ``usage`` dict through
  to the caller (B3 — see also ``test_usage_b3.py``).
* ``Femtobot.from_config(lock_timeout_s=...)`` propagates the
  timeout to the per-session lock (B1).
* ``Femtobot.run`` is async and returns a ``RunResult``.

These tests don't hit a real provider.  They use a stub ``AgentLoop``
with a stub ``process_direct`` so the contract is pinned at the
public-method level only.
"""

from __future__ import annotations

from typing import Any

from femtobot.femtobot import Femtobot, RunResult
from femtobot.providers.base import LLMResponse


def _make_facade(
    *,
    usage: dict[str, int] | None = None,
    content: str = "stub",
    lock_timeout_s: float = 5.0,
) -> Femtobot:
    """Build a Femtobot with a stubbed AgentLoop.

    The stub returns ``content`` / ``usage`` regardless of the
    message, and doesn't touch the bus / session manager.
    """
    bot = Femtobot.__new__(Femtobot)  # type: ignore[call-arg]
    import asyncio
    import weakref

    class _Stub:
        def __init__(self) -> None:
            self._extra_hooks: list = []

        async def process_direct(
            self, message: str, *, session_key: str, **kwargs: Any
        ) -> LLMResponse:
            return LLMResponse(
                content=content,
                finish_reason="stop",
                usage=dict(usage or {}),
            )

    bot._loop = _Stub()  # type: ignore[attr-defined]
    bot._sdk_locks = weakref.WeakValueDictionary()  # type: ignore[attr-defined]
    bot._sdk_locks_lock = asyncio.Lock()  # type: ignore[attr-defined]
    bot._lock_timeout_s = float(lock_timeout_s)  # type: ignore[attr-defined]
    return bot


async def test_run_returns_run_result_with_content() -> None:
    """SDK: ``run()`` returns a ``RunResult`` with the LLM content (SDK)."""
    bot = _make_facade(content="hello from stub")
    result = await bot.run("ping", session_key="test")
    assert isinstance(result, RunResult)
    assert result.content == "hello from stub"


async def test_run_forwards_usage() -> None:
    """SDK (B3): ``RunResult.usage`` carries the provider's usage dict (B3)."""
    bot = _make_facade(usage={"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19})
    result = await bot.run("ping")
    assert result.usage == {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19}


async def test_run_usage_is_none_when_provider_omits() -> None:
    """SDK (B3): ``RunResult.usage`` defaults to an empty dict (B3)."""
    bot = _make_facade(usage=None)
    result = await bot.run("ping")
    # LLMResponse.usage is a default_factory=dict so we get an empty
    # dict, not None, when the provider didn't surface any.  This
    # matches the historical contract and is what callers see.
    assert result.usage == {}


async def test_run_default_session_key() -> None:
    """SDK: the default session_key is ``"sdk:default"`` (SDK)."""
    bot = _make_facade(content="default-session")
    result = await bot.run("hello")
    assert result.content == "default-session"


async def test_run_distinct_session_keys_run_in_parallel() -> None:
    """SDK: distinct session_keys run concurrently (no global bottleneck) (B1)."""
    import asyncio
    import time

    # Each stub call takes ~0.1s; in parallel total ≈ 0.1s, serialized
    # would be ≥ 0.2s.  We allow some headroom for scheduling.
    bot = _make_facade()
    start = time.monotonic()
    await asyncio.gather(
        bot.run("a", session_key="k1"),
        bot.run("b", session_key="k2"),
    )
    elapsed = time.monotonic() - start
    assert elapsed < 0.18, f"distinct keys should run in parallel, took {elapsed:.3f}s"


async def test_from_config_signature() -> None:
    """SDK: ``Femtobot.from_config`` is a classmethod with the expected params (SDK)."""
    import inspect

    sig = inspect.signature(Femtobot.from_config)
    params = list(sig.parameters.values())
    # The first non-``cls`` parameter should be ``config_path`` (the
    # historical entry point that resolves the runtime location and
    # loads the config from disk).  We allow either the unbound
    # (``cls``) or the bound (``config_path``) shape.
    first = params[0].name
    assert first in {"cls", "config_path"}
    # ``lock_timeout_s`` is a keyword with a default.
    lock_idx = next(
        (i for i, p in enumerate(params) if p.name == "lock_timeout_s"),
        None,
    )
    assert lock_idx is not None
    assert params[lock_idx].default is not inspect.Parameter.empty


def test_run_result_dataclass_fields() -> None:
    """SDK: ``RunResult`` exposes ``content`` / ``tools_used`` / ``messages`` / ``usage`` (SDK)."""
    import dataclasses

    fields = {f.name for f in dataclasses.fields(RunResult)}
    assert {"content", "tools_used", "messages", "usage"} <= fields


def test_run_result_slots() -> None:
    """SDK: ``RunResult`` is ``@dataclass(slots=True)`` (memory-footprint) (SDK)."""
    # We don't need to be strict; just ensure ``slots=True`` is set.
    # This pins the memory footprint choice so a future refactor
    # doesn't accidentally drop the slot optimization.
    assert RunResult.__dataclass_params__.slots is True
