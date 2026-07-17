"""High-level programmatic interface to Femtobot."""

from __future__ import annotations

import asyncio
import os
import shutil
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from femtobot.agent.hook import AgentHook, SDKCaptureHook
from femtobot.agent.loop import AgentLoop


def _warn_missing_mcp_executables(config: Any) -> None:
    """Log a warning when an MCP server's executable is not on PATH.

    Added in PR 6.1 of the longlogs remediation plan. The check is
    best-effort: it inspects ``config.tools.mcp_servers`` and only
    fires for stdio servers (URL-based ones are out of scope). The
    goal is to surface the "fastmcp vs percival-osm-mcp" typo at
    SDK init time so users do not have to wait for the agent loop's
    startup log to figure out why their MCP server is not connecting.

    Never raises — the SDK remains usable even when no MCP server
    can connect.
    """
    mcp_cfg = getattr(getattr(config, "tools", None), "mcp_servers", None) or {}
    for name, server in mcp_cfg.items():
        transport = getattr(server, "type", None) or "stdio"
        if transport != "stdio":
            continue
        command = getattr(server, "command", None)
        if not command:
            continue
        # If the command is an absolute path, check it exists; otherwise
        # only check PATH lookup.
        cmd_path = Path(command)
        if cmd_path.is_absolute():
            if not cmd_path.exists():
                logger.warning(
                    "MCP server '{name}' configured with command '{cmd}' "
                    "but the file does not exist. "
                    "Update tools.mcp_servers.{name}.command in config.json.",
                    name=name,
                    cmd=command,
                )
            continue
        # Bare executable name: rely on shutil.which.
        if shutil.which(command) is None and not any(
            os.path.isdir(p) for p in os.environ.get("PATH", "").split(os.pathsep)
        ):
            logger.warning(
                "MCP server '{name}' configured with command '{cmd}' "
                "but the executable is not on PATH. "
                "Install the server (e.g. ``pip install percival-osm``) "
                "or update tools.mcp_servers.{name}.command in config.json.",
                name=name,
                cmd=command,
            )


@dataclass(slots=True)
class RunResult:
    """Result of a single agent run."""

    content: str
    tools_used: list[str]
    messages: list[dict[str, Any]]
    usage: dict[str, int] | None = None  # B3: real provider usage (prompt/completion/total)


# Default lock-acquisition timeout for concurrent SDK runs on the same
# session_key.  5s matches the API server behavior and is short enough
# to surface a 409 quickly while long enough to absorb a real LLM call
# already in progress.
_DEFAULT_SDK_LOCK_TIMEOUT_S = 5.0


class Femtobot:
    """Programmatic facade for running the Femtobot agent.

    Usage::

        bot = Femtobot.from_config()
        result = await bot.run("Summarize this repo", hooks=[MyHook()])
        print(result.content)
    """

    def __init__(
        self,
        loop: AgentLoop,
        *,
        lock_timeout_s: float = _DEFAULT_SDK_LOCK_TIMEOUT_S,
    ) -> None:
        self._loop = loop
        # B1: per-session_key locks so concurrent ``Femtobot.run`` calls
        # with the same key are serialized (avoiding interleaved history
        # writes).  ``WeakValueDictionary`` lets the lock be GC'd when
        # the last reference is dropped — combined with the
        # ``WeakKeyDictionary`` of last-known locks keyed on
        # ``Femtobot`` instances, sessions that go quiet don't leak.
        self._sdk_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )
        self._sdk_locks_lock = asyncio.Lock()
        self._lock_timeout_s = float(lock_timeout_s)

    @classmethod
    def from_config(
        cls,
        config_path: str | Path | None = None,
        *,
        workspace: str | Path | None = None,
        lock_timeout_s: float = _DEFAULT_SDK_LOCK_TIMEOUT_S,
    ) -> Femtobot:
        """Create a Femtobot instance from a config file.

        Args:
            config_path: Path to ``config.json``.  Defaults to
                ``.femtobot/config.json``.
            workspace: Override the workspace directory from config.
            lock_timeout_s: Max seconds ``run()`` waits to acquire the
                per-session_key lock before raising ``asyncio.TimeoutError``
                (B1).  Set to 0 to disable locking (not recommended).
        """
        from femtobot.config.loader import load_config, resolve_config_env_vars
        from femtobot.config.schema import Config

        resolved: Path | None = None
        if config_path is not None:
            resolved = Path(config_path).expanduser().resolve()
            if not resolved.exists():
                raise FileNotFoundError(f"Config not found: {resolved}")

        config: Config = resolve_config_env_vars(load_config(resolved))
        if workspace is not None:
            config.agents.defaults.workspace = str(Path(workspace).expanduser().resolve())

        # PR 6.1 (longlogs remediation): warn (do not raise) when an
        # MCP server is configured but its executable is not on PATH.
        # This makes the "fastmcp vs percival-osm-mcp" typo visible at
        # SDK init time instead of burying the failure in the agent
        # loop's startup log.
        _warn_missing_mcp_executables(config)

        loop = AgentLoop.from_config(
            config,
        )
        return cls(loop, lock_timeout_s=lock_timeout_s)

    async def _acquire_session_lock(self, session_key: str) -> asyncio.Lock:
        """Return the asyncio.Lock for *session_key*, creating it on demand (B1)."""
        # Fast path: lock already exists.  ``WeakValueDictionary`` raises
        # ``KeyError`` when the value was GC'd (it stores weak refs).
        try:
            return self._sdk_locks[session_key]
        except KeyError:
            pass
        # Slow path: serialize creation so two concurrent callers don't
        # each create a fresh lock and race against the old one.
        async with self._sdk_locks_lock:
            try:
                return self._sdk_locks[session_key]
            except KeyError:
                lock = asyncio.Lock()
                self._sdk_locks[session_key] = lock
                return lock

    async def run(
        self,
        message: str,
        *,
        session_key: str = "sdk:default",
        hooks: list[AgentHook] | None = None,
    ) -> RunResult:
        """Run the agent once and return the result.

        Args:
            message: The user message to process.
            session_key: Session identifier for conversation isolation.
                Different keys get independent history.
            hooks: Optional lifecycle hooks for this run.

        Raises:
            asyncio.TimeoutError: if the per-session lock cannot be
                acquired within ``lock_timeout_s`` (B1).
        """
        capture = SDKCaptureHook()
        prev = self._loop._extra_hooks
        base_hooks = list(hooks) if hooks is not None else list(prev or [])
        self._loop._extra_hooks = [capture, *base_hooks]
        # Audit (J14 of the v0.1.1 sixth-pass review): validate
        # ``_lock_timeout_s`` BEFORE the lock path so a NaN/inf
        # value (which would have taken the ``else`` branch and
        # called ``_acquire_session_lock``) raises
        # ``ValueError`` early.  ``math.isfinite`` is False for
        # NaN and both infinities; we also reject negatives
        # explicitly.
        import math

        # Audit (J14): check the full set of bad values, not
        # just ``> 0`` (NaN fails both ``> 0`` and ``<= 0``
        # comparisons, so the first guard must reject *all*
        # non-finite and negative values).
        if (
            not math.isfinite(self._lock_timeout_s)
            or self._lock_timeout_s < 0
        ):
            raise ValueError(
                f"lock_timeout_s must be a finite non-negative number;"
                f" got {self._lock_timeout_s!r}"
            )
        try:
            # B1: serialize concurrent calls on the same session_key.
            if self._lock_timeout_s <= 0:
                response = await self._loop.process_direct(
                    message,
                    session_key=session_key,
                )
            else:
                # Audit (J3 of the v0.1.1 sixth-pass review):
                # ``_sdk_locks`` is a ``WeakValueDictionary`` so
                # the lock value can be GC'd between the
                # ``_acquire_session_lock`` return and the
                # ``lock.acquire()`` call below.  If that
                # happens, ``acquire()`` operates on a fresh
                # lock (uncontended) and the original lock is
                # never released, breaking serialization.
                # We pin a strong reference in a local
                # variable so the GC cannot collect the lock
                # while we're waiting for it.
                lock = await self._acquire_session_lock(session_key)
                # ``_keep_alive`` is a strong reference
                # retained for the lifetime of this function
                # call; assigning it to ``self._sdk_locks[key]``
                # is not enough because that only stores a
                # weak reference.  The local ``lock`` is the
                # strong reference.
                _keep_alive = lock
                try:
                    await asyncio.wait_for(lock.acquire(), timeout=self._lock_timeout_s)
                except asyncio.TimeoutError:
                    logger.warning(
                        "Femtobot.run timed out acquiring session lock for {} "
                        "after {:.1f}s",
                        session_key,
                        self._lock_timeout_s,
                    )
                    raise
                try:
                    response = await self._loop.process_direct(
                        message,
                        session_key=session_key,
                    )
                finally:
                    lock.release()
        finally:
            # Always restore the previous ``_extra_hooks`` so the
            # per-run capture hook doesn't leak into a subsequent run
            # (or follow-up operation) on the same Femtobot instance.
            self._loop._extra_hooks = prev

        content = (response.content if response else None) or ""
        # B3: forward real usage if the provider supplied it.
        usage = None
        try:
            usage = getattr(response, "usage", None)
        except Exception:  # pragma: no cover - defensive
            usage = None
        return RunResult(
            content=content,
            tools_used=capture.tools_used,
            messages=capture.messages,
            usage=usage,
        )
