"""HTTP handlers for the ``async_goal`` long-task contract.

These handlers are mounted by ``api/server.py`` when the configuration
flag ``agents.defaults.longTask.byDefault=true`` (or the operator
explicitly enables async goals).  They are deliberately minimal: the
admission path returns ``202 Accepted`` immediately and the actual
work happens on a background task tracked by a per-session queue.

Endpoints:

* ``POST /v1/goals`` — admit a long-task job and return its
  ``goal_id`` plus polling/event URLs.
* ``GET  /v1/goals/{goal_id}`` — return the job status snapshot.
* ``GET  /v1/goals/{goal_id}/events`` — SSE / NDJSON stream of events.
* ``POST /v1/goals/{goal_id}/answer`` — resume a goal that's waiting
  on an ``ask_orchestrator`` reply.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Mapping

from aiohttp import web

from femtobot.api.goal_runtime import (
    GoalEvent,
    GoalEventKind,
    GoalJob,
    GoalJobStatus,
    create_goal_job,
    serialize_goal_event,
    terminal_status,
)
from femtobot.api.goal_schemas import (
    AsyncGoalAccepted,
    AsyncGoalAnswerRequest,
    AsyncGoalRequest,
    AsyncGoalStatus,
)
from femtobot.session.pending_asks import (
    AskStatus,
    list_pending_asks,
    update_pending_ask,
)


# ---------------------------------------------------------------------------
# Job registry — keyed by goal_id
# ---------------------------------------------------------------------------


class GoalRegistry:
    """In-process registry of active goal jobs.

    This is intentionally not persistent — when the process restarts,
    the caller must poll the originating session to recover state.  The
    ``pending_asks`` blob in session metadata *is* persistent, so a
    restart can resume an interrupted job.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, GoalJob] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._events: dict[str, asyncio.Queue[GoalEvent]] = {}

    def create(self, *, session_key: str, objective: str | None = None) -> GoalJob:
        job = create_goal_job(session_key=session_key, objective=objective)
        self._jobs[job.goal_id] = job
        self._locks[job.goal_id] = asyncio.Lock()
        self._events[job.goal_id] = asyncio.Queue()
        self._publish(
            job.goal_id,
            GoalEvent.new(goal_id=job.goal_id, kind=GoalEventKind.CREATED),
        )
        return job

    def get(self, goal_id: str) -> GoalJob | None:
        return self._jobs.get(goal_id)

    def list(self) -> list[GoalJob]:
        return list(self._jobs.values())

    def lock(self, goal_id: str) -> asyncio.Lock:
        lock = self._locks.get(goal_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[goal_id] = lock
        return lock

    def events_queue(self, goal_id: str) -> asyncio.Queue[GoalEvent]:
        queue = self._events.get(goal_id)
        if queue is None:
            queue = asyncio.Queue()
            self._events[goal_id] = queue
        return queue

    def _publish(self, goal_id: str, event: GoalEvent) -> None:
        job = self._jobs.get(goal_id)
        if job is None:
            return
        job.events.append(event)
        # Trim event log to avoid unbounded growth in long-running jobs.
        if len(job.events) > 1024:
            job.events = job.events[-512:]
        # The events queue is unbounded by default; ``put_nowait`` only
        # raises ``QueueFull`` when the queue was constructed with a
        # ``maxsize`` (we don't do that today, but defensive code is
        # cheap).  Logging the warning surfaces a misconfiguration
        # without crashing the publisher.
        try:
            self._events[goal_id].put_nowait(event)
        except asyncio.QueueFull:
            from loguru import logger

            logger.warning(
                "GoalRegistry event queue full for goal_id={} (size={}); "
                "stream subscribers will miss this event.",
                goal_id,
                self._events[goal_id].qsize(),
            )

    def publish(self, goal_id: str, event: GoalEvent) -> None:
        """Publish *event* to the registry.

        Kept as a thin alias of :meth:`_publish` so external callers do
        not need to depend on the underscore-prefixed internal name.
        """
        self._publish(goal_id, event)

    def update_status(self, goal_id: str, status: GoalJobStatus) -> None:
        job = self._jobs.get(goal_id)
        if job is None:
            return
        # Idempotency: avoid emitting redundant STATUS_CHANGED/FINAL
        # events when the status hasn't actually transitioned.
        if job.status == status:
            return
        job.status = status
        # Use the same ISO-with-ms helper used elsewhere — ``time.strftime``
        # silently drops milliseconds and can also be off-by-one-second
        # between two adjacent calls.
        iso_now = (
            datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        job.updated_at = iso_now
        self._publish(
            goal_id,
            GoalEvent.new(
                goal_id=goal_id,
                kind=GoalEventKind.STATUS_CHANGED,
                data={"status": status.value},
            ),
        )
        if terminal_status(status):
            self._publish(
                goal_id,
                GoalEvent.new(
                    goal_id=goal_id,
                    kind=GoalEventKind.FINAL,
                    data={"status": status.value},
                ),
            )

    def cleanup_terminal(self, *, keep_recent: int = 64) -> int:
        """Drop registry state for terminal jobs to bound memory growth.

        Long-running processes admit goals continuously; without this
        cleanup the ``_jobs`` / ``_locks`` / ``_events`` dicts grow
        without bound.  We retain the most recently transitioned
        ``keep_recent`` jobs so polling clients can still inspect the
        recent past via ``GET /v1/goals/{goal_id}``.

        Returns the number of jobs removed.
        """
        if keep_recent < 0:
            raise ValueError("keep_recent must be >= 0")
        # Sort by ``updated_at`` (ISO timestamp) ascending — oldest
        # transition first.  ``sorted`` is stable, so jobs sharing the
        # exact same timestamp keep their insertion order (FIFO).
        candidates = sorted(
            (j for j in self._jobs.values() if terminal_status(j.status)),
            key=lambda j: j.updated_at,
        )
        # We want to KEEP ``keep_recent`` jobs (the newest transitions)
        # and drop everything older.  ``candidates[-keep_recent:]`` is
        # the tail we keep; the complement is what we drop.
        keep_count = min(keep_recent, len(candidates))
        to_remove = candidates[: len(candidates) - keep_count] if keep_count else candidates
        for job in to_remove:
            self._jobs.pop(job.goal_id, None)
            self._locks.pop(job.goal_id, None)
            self._events.pop(job.goal_id, None)
        return len(to_remove)


# ---------------------------------------------------------------------------
# HTTP handlers
# ---------------------------------------------------------------------------


def _error(status: int, message: str) -> web.Response:
    return web.json_response({"error": {"message": message}}, status=status)


def _accepted_response(goal: GoalJob, request: web.Request) -> web.Response:
    """Build a ``202 Accepted`` response with the operator-facing URLs.

    The base URL is derived from ``request.url`` by stripping the path
    suffix — we use ``request.scheme + request.host`` rather than a
    string split, so a URL like ``/v1something/foo`` (theoretical, but
    defensive) cannot produce a wrong base.
    """
    base = f"{request.scheme}://{request.host}"
    payload = AsyncGoalAccepted(
        session_id=goal.session_key.split(":", 1)[-1] if goal.session_key else "",
        goal_id=goal.goal_id,
        poll_url=f"{base}/v1/goals/{goal.goal_id}",
        events_url=f"{base}/v1/goals/{goal.goal_id}/events",
        answer_url=f"{base}/v1/goals/{goal.goal_id}/answer",
        accepted_at=goal.created_at,
    )
    return web.json_response(payload.to_dict(), status=202)


async def handle_create_goal(request: web.Request) -> web.Response:
    """``POST /v1/goals`` — admit a long-task job."""
    registry: GoalRegistry = request.app["goal_registry"]
    try:
        body = await request.json()
    except Exception:
        return _error(400, "Invalid JSON body")
    if not isinstance(body, dict):
        return _error(400, "Body must be a JSON object.")

    # Validate field types *before* constructing the dataclass so callers
    # get a clean 400 instead of a confusing ``TypeError`` deep in the
    # code path.  ``list(...)`` on a dict yields keys, so a malformed
    # ``messages`` (e.g. an object) would silently produce a junk list.
    raw_messages = body.get("messages")
    if raw_messages is None:
        messages: list = []
    elif isinstance(raw_messages, list):
        messages = list(raw_messages)
    else:
        return _error(400, "Error: 'messages' must be a list.")

    raw_metadata = body.get("metadata")
    if raw_metadata is None:
        metadata: dict = {}
    elif isinstance(raw_metadata, dict):
        metadata = dict(raw_metadata)
    else:
        return _error(400, "Error: 'metadata' must be an object.")

    req = AsyncGoalRequest(
        model=body.get("model"),
        messages=messages,
        session_id=body.get("session_id"),
        objective=body.get("objective"),
        metadata=metadata,
        stream=False,
    )
    err = req.validate()
    if err:
        return _error(400, err)
    session_key = f"api:{req.session_id}"
    job = registry.create(session_key=session_key, objective=req.objective)

    # Attach the work — the admission endpoint must publish an inbound
    # that triggers the agent loop, otherwise the goal sits idle in the
    # registry until the operator separately calls /v1/goals/{id}/answer.
    # We rely on the optional ``agent_loop`` reference the app wires up
    # during boot; when it is missing (e.g. unit tests, dry-run mode)
    # we still admit the goal so the operator can poll status.
    agent_loop = request.app.get("agent_loop")
    if agent_loop is not None and getattr(agent_loop, "bus", None) is not None:
        try:
            from femtobot.bus.events import InboundMessage

            # Choose a content seed: prefer an explicit objective, else
            # join the user messages into a single bootstrap prompt.
            if req.objective:
                content = req.objective
            else:
                content = "\n".join(
                    str(m.get("content") or "")
                    for m in req.messages
                    if isinstance(m, Mapping)
                )
            inbound = InboundMessage(
                channel="api",
                sender_id="supervisor",
                chat_id=req.session_id,
                content=content or "/goal",
                metadata={
                    "goal_requested": True,
                    "original_command": "/goal",
                    "async_goal_id": job.goal_id,
                    **req.metadata,
                },
            )
            await agent_loop.bus.publish_inbound(inbound)
            registry.update_status(job.goal_id, GoalJobStatus.RUNNING)
        except (RuntimeError, asyncio.TimeoutError, ConnectionError) as exc:
            # Transport / queue-level failures are recoverable: the job
            # is admitted and the operator can drive progress via
            # /v1/goals/{id}/answer.  Programmer errors (TypeError,
            # AttributeError, …) must propagate so they're caught in
            # tests and so misconfigurations don't silently lose work.
            from loguru import logger

            logger.warning(
                "handle_create_goal failed to publish bootstrap inbound "
                "(goal_id={}): {}. Job remains admitted; the operator "
                "must drive progress manually.",
                job.goal_id,
                exc,
            )

    return _accepted_response(job, request)


async def handle_get_goal(request: web.Request) -> web.Response:
    """``GET /v1/goals/{goal_id}`` — return job status."""
    registry: GoalRegistry = request.app["goal_registry"]
    goal_id = request.match_info["goal_id"]
    job = registry.get(goal_id)
    if job is None:
        return _error(404, "Goal not found")
    status = AsyncGoalStatus(
        status=job.status.value,
        session_id=job.session_key.split(":", 1)[-1],
        goal_id=job.goal_id,
        objective=job.objective,
        elapsed_s=job.elapsed_s(),
        final_content=job.final_content,
        error=job.error,
    )
    return web.json_response(status.to_dict())


async def handle_goal_events(request: web.Request) -> web.Response:
    """``GET /v1/goals/{goal_id}/events`` — NDJSON stream.

    Streams the entire event history, then keeps the connection open
    and forwards any new events published via :meth:`GoalRegistry.publish`
    until either the goal reaches a terminal state or the client
    disconnects.

    Two special query parameters control the connection:

    * ``?replay=0`` — skip replay of historical events, only stream live ones.
    * ``?idle_timeout_s=<seconds>`` — close the connection after this many
      seconds without new events.  Defaults to 30s.
    """
    registry: GoalRegistry = request.app["goal_registry"]
    goal_id = request.match_info["goal_id"]
    job = registry.get(goal_id)
    if job is None:
        return _error(404, "Goal not found")
    # Parse optional query parameters defensively — clients may pass
    # strings or floats; reject obvious garbage instead of crashing.
    try:
        replay = request.query.get("replay", "1") != "0"
    except Exception:
        replay = True
    try:
        idle_timeout_s = float(request.query.get("idle_timeout_s", "30"))
    except (TypeError, ValueError):
        idle_timeout_s = 30.0
    idle_timeout_s = max(0.0, min(idle_timeout_s, 600.0))

    resp = web.StreamResponse()
    resp.content_type = "application/x-ndjson"
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    await resp.prepare(request)

    # Replay historical events first.
    if replay:
        for evt in list(job.events):
            await resp.write(serialize_goal_event(evt).encode("utf-8") + b"\n")

    # If the job is already terminal, send a trailing newline to flush
    # any buffered HTTP framing and close the connection.
    if job.is_terminal:
        await resp.write(b"\n")
        await resp.write_eof()
        return resp

    # Subscribe to live updates.  Each iteration waits for either a
    # new event (queue.get) or the idle timeout — whichever comes first.
    queue = registry.events_queue(goal_id)
    try:
        while not job.is_terminal:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=idle_timeout_s)
            except asyncio.TimeoutError:
                # Heartbeat — keeps proxies from closing the connection
                # and signals liveness to long-polling clients.
                await resp.write(b"\n")
                continue
            await resp.write(serialize_goal_event(event).encode("utf-8") + b"\n")
            if event.kind is GoalEventKind.FINAL:
                break
    except (ConnectionResetError, asyncio.CancelledError):
        # Client disconnected; nothing more to do.
        return resp
    finally:
        # Send a final empty line so NDJSON parsers flush.
        try:
            await resp.write(b"\n")
            await resp.write_eof()
        except (ConnectionResetError, asyncio.CancelledError):
            pass

    return resp


async def handle_post_answer(request: web.Request) -> web.Response:
    """``POST /v1/goals/{goal_id}/answer`` — submit an answer for a pending ask."""
    registry: GoalRegistry = request.app["goal_registry"]
    agent_loop = request.app["agent_loop"]
    goal_id = request.match_info["goal_id"]
    job = registry.get(goal_id)
    if job is None:
        return _error(404, "Goal not found")
    try:
        body = await request.json()
    except Exception:
        return _error(400, "Invalid JSON body")
    if not isinstance(body, dict):
        return _error(400, "Body must be a JSON object.")

    raw_metadata = body.get("metadata")
    if raw_metadata is None:
        metadata: dict = {}
    elif isinstance(raw_metadata, dict):
        metadata = dict(raw_metadata)
    else:
        return _error(400, "Error: 'metadata' must be an object.")

    payload = AsyncGoalAnswerRequest(
        correlation_id=body.get("correlation_id"),
        response=str(body.get("response") or ""),
        metadata=metadata,
    )
    err = payload.validate()
    if err:
        return _error(400, err)

    # Serialize concurrent answers per goal — without this lock, two
    # orchestrators racing to answer the same ask would both see the
    # ask as pending and both publish a resume inbound.
    async with registry.lock(goal_id):
        # Persist the answer in session metadata and resume the goal.
        session = agent_loop.sessions.get_or_create(job.session_key)
        md = dict(session.metadata or {})
        asks = list_pending_asks(md)
        target = None
        if payload.correlation_id:
            for a in asks:
                if a.correlation_id == payload.correlation_id:
                    target = a
                    break
        if target is None:
            # Best-effort fallback — find the first pending ask.
            for a in asks:
                if a.status.value == "pending":
                    target = a
                    break
        if target is None:
            return _error(409, "No pending ask matches this goal.")
        changed = update_pending_ask(
            md,
            target.correlation_id,
            status=AskStatus.ANSWERED,
            response=payload.response,
        )
        if not changed:
            # The ask was already answered (or timed out) between the
            # caller's request and our lock acquisition — don't enqueue
            # a second resume inbound.
            return _error(409, "Ask was already finalized.")

        # Clear the "waiting on ask_orchestrator" marker *before* the
        # inbound is published so the worker reads consistent state.
        from femtobot.session.goal_state import clear_goal_waiting

        clear_goal_waiting(md)
        session.metadata = md

        # Persist the answer to disk before publishing the resume
        # inbound — otherwise a crash between the API response and the
        # next save would silently lose the operator's answer.
        agent_loop.sessions.save(session)

        registry.publish(
            goal_id,
            GoalEvent.new(
                goal_id=goal_id,
                kind=GoalEventKind.ASK_ANSWERED,
                data={"correlation_id": target.correlation_id, "response": payload.response},
            ),
        )

        # Enqueue an inbound that resumes the goal in this session.
        from femtobot.bus.events import InboundMessage

        inbound = InboundMessage(
            channel="api",
            sender_id="orchestrator",
            chat_id=job.session_key.split(":", 1)[-1] or "default",
            content=f"[answer correlation_id={target.correlation_id}] {payload.response}",
            metadata={
                "goal_requested": True,
                "original_command": "/goal",
                "ask_answer_correlation_id": target.correlation_id,
                "ask_answer_response": payload.response,
            },
        )
        # ``publish_inbound`` is async — missing ``await`` here would
        # silently drop the inbound (the coroutine is never awaited) and
        # the worker would never see the resume signal.
        await agent_loop.bus.publish_inbound(inbound)
        return web.json_response(
            {
                "status": "accepted",
                "goal_id": goal_id,
                "correlation_id": target.correlation_id,
            }
        )


# ---------------------------------------------------------------------------
# Mount helpers
# ---------------------------------------------------------------------------


def register_goal_routes(app: web.Application) -> None:
    """Mount the long-task HTTP routes onto *app*."""
    if "goal_registry" not in app:
        app["goal_registry"] = GoalRegistry()
    app.router.add_post("/v1/goals", handle_create_goal)
    app.router.add_get("/v1/goals/{goal_id}", handle_get_goal)
    app.router.add_get("/v1/goals/{goal_id}/events", handle_goal_events)
    app.router.add_post("/v1/goals/{goal_id}/answer", handle_post_answer)


__all__ = [
    "GoalRegistry",
    "handle_create_goal",
    "handle_get_goal",
    "handle_goal_events",
    "handle_post_answer",
    "register_goal_routes",
]