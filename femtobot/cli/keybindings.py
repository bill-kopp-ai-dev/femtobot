"""Custom keybindings system with hot-reload from JSON files.

Inspired by Claude Code's keybindings.json (see
``FEMTOBOT_CLI_REFACTOR_PLAN.md`` Camada 2, T2.1).

Architecture
------------
Each keybinding is a JSON object with the following shape::

    {
        "context": "chat",
        "key": "ctrl+r",
        "action": "history:reverse-search",
        "then": "ctrl+k"     // optional: chord
    }

Context names (``chat``, ``global``, ``completion``) gate which bindings
are active.  Actions are dispatched by :class:`ActionDispatcher`.

The watcher uses ``watchdog`` for real-time reload; if watchdog is
unavailable it falls back to a simple mtime-polling thread.

Usage
-----
Call :func:`load_keybindings` with a file path and a dispatcher callback::

    def on_action(action: str, event):
        ...

    kb = load_keybindings(Path("~/.femtobot/keybindings.json"), on_action)

:class:`KeybindingsWatcher` keeps the bindings live::

    watcher = KeybindingsWatcher(kb, Path("~/.femtobot/keybindings.json"))
    await watcher.watch()   # runs until cancelled
"""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@dataclass
class KeyBinding:
    """A single key binding parsed from JSON."""

    context: str = "global"  # chat | global | completion | help
    key: str = ""  # e.g. "ctrl+r", "alt+p", "f1"
    action: str = ""
    then: str | None = None  # optional chord second key

    def is_chord(self) -> bool:
        return self.then is not None

    def primary_keys(self) -> list[str]:
        return [k.strip() for k in self.key.split("+")]

    def chord_keys(self) -> list[str] | None:
        if not self.then:
            return None
        return [k.strip() for k in self.then.split("+")]


@dataclass
class KeybindingsConfig:
    """Parsed content of a ``keybindings.json`` file."""

    bindings: list[KeyBinding] = field(default_factory=list)
    _path: Path | None = field(default=None, repr=False)

    def for_context(self, ctx: str) -> list[KeyBinding]:
        return [b for b in self.bindings if b.context == ctx]

    def lookup(self, ctx: str, key: str) -> KeyBinding | None:
        for b in self.for_context(ctx):
            if b.key.lower() == key.lower():
                return b
        return None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_keybindings(raw: dict) -> list[KeyBinding]:
    """Parse a JSON-decoded keybindings object into a list of :class:`KeyBinding`."""
    bindings_data = raw if isinstance(raw, list) else raw.get("bindings", [])
    result = []
    for entry in bindings_data:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key", "")).strip()
        if not key:  # skip entries without a key
            continue
        result.append(
            KeyBinding(
                context=str(entry.get("context", "global")).lower(),
                key=key,
                action=str(entry.get("action", "")),
                then=str(entry.get("then") or "").strip() or None,
            )
        )
    return result


def load_keybindings_file(path: Path) -> KeybindingsConfig:
    """Load and parse a ``keybindings.json`` file.

    Returns an empty config if the file does not exist or is invalid JSON.
    """
    if not path.exists():
        return KeybindingsConfig()
    try:
        raw = json.loads(path.read_text("utf-8"))
        bindings = parse_keybindings(raw)
        return KeybindingsConfig(bindings=bindings, _path=path)
    except (json.JSONDecodeError, OSError):
        return KeybindingsConfig()


# ---------------------------------------------------------------------------
# Dispatcher helpers
# ---------------------------------------------------------------------------

ActionDispatcher = Callable[[str], bool | None]
"""Callback invoked with an action name when a keybinding is triggered.

Should return ``True`` if the action was handled, ``False`` if not
recognised, or ``None`` to fall through to the default behaviour.

Predefined action names:
  app:interrupt    — send KeyboardInterrupt to the running turn
  app:exit        — exit the REPL
  app:redraw      — force a screen redraw
  chat:cancel     — cancel the current response
  chat:submit     — submit the current input
  chat:newline    — insert a newline (in multiline)
  chat:clear-input — clear the current input buffer
  history:prev    — navigate to previous history entry
  history:next    — navigate to next history entry
  completion:accept  — accept the current autocomplete suggestion
  completion:next    — next autocomplete suggestion
  bash:execute   — activate bash mode
  file:mention    — activate file mention mode
  model:open-picker — open the /model picker
  effort:cycle    — cycle effort level
"""


# ---------------------------------------------------------------------------
# Watcher
# ---------------------------------------------------------------------------

DEFAULT_POLL_INTERVAL_S = 1.0
"""Polling interval when watchdog is unavailable."""


class KeybindingsWatcher:
    """Watch a ``keybindings.json`` file and reload on change.

    Uses ``watchdog`` when available for efficient real-time notifications.
    Falls back to a background thread that polls ``mtime`` at
    :data:`DEFAULT_POLL_INTERVAL_S`.
    """

    def __init__(
        self,
        config: KeybindingsConfig,
        path: Path,
        reload_callback: Callable[[KeybindingsConfig], None] | None = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL_S,
    ):
        self._config = config
        self._path = path
        self._reload_callback = reload_callback or (lambda cfg: None)
        self._poll_interval = poll_interval
        self._running = False
        self._stop_event = asyncio.Event()
        self._lock = threading.Lock()
        self._watchdog_observer = None

    def _reload(self) -> None:
        with self._lock:
            new_cfg = load_keybindings_file(self._path)
            self._config = new_cfg
        self._reload_callback(new_cfg)

    @property
    def config(self) -> KeybindingsConfig:
        return self._config

    async def watch(self) -> None:
        """Start watching. Returns when :meth:`stop` is called."""
        self._running = True
        try:
            obs = self._try_start_watchdog()
            if obs:
                self._watchdog_observer = obs
                # watchdog observer runs in background thread; block until stop
                await self._stop_event.wait()
            else:
                await self._poll_loop()
        finally:
            self._running = False
            self._cleanup()

    def stop(self) -> None:
        """Signal the watcher to stop."""
        self._stop_event.set()

    # ------------------------------------------------------------------
    # watchdog path
    # ------------------------------------------------------------------

    def _try_start_watchdog(self):
        try:
            from watchdog.observers import Observer
        except Exception:
            return None

        class _Handler:
            def __init__(self, watcher):
                self._watcher = watcher

            def on_modified(self, event):
                if event.src_path == str(self._watcher._path):
                    self._watcher._reload()

        obs = Observer()
        obs.schedule(_Handler(self), str(self._path.parent), recursive=False)
        obs.start()
        return obs

    # ------------------------------------------------------------------
    # polling fallback
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        last_mtime = self._mtime()
        while not self._stop_event.is_set():
            await asyncio.sleep(self._poll_interval)
            current_mtime = self._mtime()
            if current_mtime is not None and current_mtime != last_mtime:
                last_mtime = current_mtime
                self._reload()

    def _mtime(self) -> float | None:
        try:
            return self._path.stat().st_mtime
        except OSError:
            return None

    # ------------------------------------------------------------------
    # cleanup
    # ------------------------------------------------------------------

    def _cleanup(self) -> None:
        if self._watchdog_observer:
            self._watchdog_observer.stop()
            self._watchdog_observer.join(timeout=2.0)
            self._watchdog_observer = None
