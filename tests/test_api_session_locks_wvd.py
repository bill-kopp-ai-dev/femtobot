"""``api/server.py`` session_locks no longer leaks (v0.0.7 second-pass).

Audit item 7 of the v0.0.7 second-pass review: the OpenAI-compat
HTTP server used a regular ``dict[str, asyncio.Lock]`` keyed by
``session_id``.  Each new ``session_id`` (e.g. UUID per browser
tab) leaked a Lock object for the lifetime of the server.

Fix: switch to ``weakref.WeakValueDictionary``.  The request
handler holds a strong ref to the Lock for the duration of the
request, so the WVD never GC's a lock mid-acquire; the lock
becomes collectible the moment the request ends.

We pin:

* the app initializer exposes a ``WeakValueDictionary`` for
  ``session_locks``,
* a fresh Lock inserted into the WVD survives while a strong
  ref is held (it does not get GC'd even after a full GC cycle),
* the lock *can* be collected when no strong ref remains.
"""

from __future__ import annotations

import asyncio
import gc
import inspect
import weakref

from femtobot.api.server import create_app


def _agent_loop_stub() -> object:
    """Minimal stub — the create_app only needs the attribute to exist."""
    return object()


def test_create_app_uses_weak_value_dictionary_for_session_locks() -> None:
    """Bounded: ``session_locks`` is a ``WeakValueDictionary`` (no leak)."""
    agent_loop = _agent_loop_stub()
    app = create_app(agent_loop, model_name="stub", request_timeout=10.0)
    locks = app["session_locks"]
    assert isinstance(locks, weakref.WeakValueDictionary)


def test_session_lock_survives_while_strongly_referenced() -> None:
    """Bounded: a strong ref keeps the lock alive across GC cycles."""
    agent_loop = _agent_loop_stub()
    app = create_app(agent_loop, model_name="stub", request_timeout=10.0)
    locks: weakref.WeakValueDictionary[str, asyncio.Lock] = app["session_locks"]
    lock = locks.get("k")
    if lock is None:
        lock = asyncio.Lock()
        locks["k"] = lock
    # Strong ref ensures the WVD doesn't GC the lock.
    _strong = lock
    gc.collect()
    assert locks.get("k") is lock


def test_session_lock_collected_when_strong_ref_dropped() -> None:
    """Bounded: the lock is collectible when the request is over."""
    agent_loop = _agent_loop_stub()
    app = create_app(agent_loop, model_name="stub", request_timeout=10.0)
    locks: weakref.WeakValueDictionary[str, asyncio.Lock] = app["session_locks"]
    # Insert a lock, drop our strong ref, and force a GC.
    lock = asyncio.Lock()
    locks["ephemeral"] = lock
    del lock
    gc.collect()
    # The WVD should no longer expose the key (lock was collected).
    assert locks.get("ephemeral") is None


def test_create_app_signature() -> None:
    """API surface: ``create_app`` keeps its 3-arg signature (audit)."""
    sig = inspect.signature(create_app)
    params = [p for p in sig.parameters.values() if p.name != "self"]
    assert [p.name for p in params] == ["agent_loop", "model_name", "request_timeout"]


def test_session_locks_facade_does_not_grow_unbounded() -> None:
    """Bounded: many session ids don't keep their locks alive forever.

    We add 100 unique session_ids, drop the local refs, and verify
    the WVD self-cleans (the original leak was that the dict
    accumulated forever).  We check that the WVD either lost the
    entries or kept fewer than the insert count.
    """
    agent_loop = _agent_loop_stub()
    app = create_app(agent_loop, model_name="stub", request_timeout=10.0)
    locks: weakref.WeakValueDictionary[str, asyncio.Lock] = app["session_locks"]
    for i in range(100):
        lk = asyncio.Lock()
        locks[f"session-{i}"] = lk
    # No strong refs to any lock.
    gc.collect()
    # We don't pin an exact count (WeakValueDictionary timing is
    # implementation-defined), but the count must be < 100.
    assert len(locks) < 100
