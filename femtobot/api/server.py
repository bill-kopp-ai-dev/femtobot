"""OpenAI-compatible HTTP API server for a fixed femtobot session.

Provides /v1/chat/completions and /v1/models endpoints.
All requests route to a single persistent API session.
"""

from __future__ import annotations

import asyncio
import contextlib
import json as _json
import time
import uuid
import weakref
from typing import Any

from aiohttp import web
from loguru import logger

from femtobot.utils.helpers import scrub_text
from femtobot.utils.runtime import EMPTY_FINAL_RESPONSE_MESSAGE

__all__ = (
    "create_app",
    "handle_chat_completions",
)


API_SESSION_KEY = "api:default"
API_CHAT_ID = "default"


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


def _error_json(status: int, message: str, err_type: str = "invalid_request_error") -> web.Response:
    return web.json_response(
        {"error": {"message": message, "type": err_type, "code": status}},
        status=status,
    )


def _chat_completion_response(
    content: str,
    model: str,
    *,
    usage: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Build a /v1/chat/completions response payload.

    B3 (REFACTOR_PLAN.md Lote B): forward real provider ``usage`` when
    available so SDK callers can track token spend.  Falls back to the
    historical zero placeholder only when the provider returned nothing
    (matches v0.0.3 behavior for upstream providers that don't surface
    usage yet).
    """
    if usage:
        normalized = {
            "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
            "total_tokens": int(
                usage.get(
                    "total_tokens",
                    (
                        int(usage.get("prompt_tokens", 0) or 0)
                        + int(usage.get("completion_tokens", 0) or 0)
                    ),
                )
                or 0
            ),
        }
    else:
        normalized = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": normalized,
    }


def _response_text(value: Any) -> str:
    """Normalize process_direct output to plain assistant text."""
    if value is None:
        return ""
    if hasattr(value, "content"):
        return str(getattr(value, "content") or "")
    return str(value)


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


def _sse_chunk(delta: str, model: str, chunk_id: str, finish_reason: str | None = None) -> bytes:
    """Format a single OpenAI-compatible SSE chunk."""
    payload = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"content": delta} if delta else {},
                "finish_reason": finish_reason,
            }
        ],
    }
    return f"data: {_json.dumps(payload)}\n\n".encode()


_SSE_DONE = b"data: [DONE]\n\n"

# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------


def _parse_json_content(body: dict) -> str:
    """Parse JSON request body. Returns text."""
    messages = body.get("messages")
    if not isinstance(messages, list) or len(messages) == 0:
        raise ValueError("Only a single user message is supported")
    message = messages[-1]
    if not isinstance(message, dict) or message.get("role") != "user":
        raise ValueError("Only a single user message is supported")

    user_content = message.get("content", "")

    if isinstance(user_content, str):
        text = user_content
    else:
        raise ValueError("Invalid content format")

    return text


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def handle_chat_completions(request: web.Request) -> web.Response:
    """POST /v1/chat/completions — supports JSON."""
    agent_loop = request.app["agent_loop"]
    timeout_s: float = request.app.get("request_timeout", 120.0)
    model_name: str = request.app.get("model_name", "Femtobot")

    stream = False
    try:
        try:
            body = await request.json()
        except Exception:
            return _error_json(400, "Invalid JSON body")
        stream = body.get("stream", False)
        requested_model = body.get("model")
        text = _parse_json_content(body)
        session_id = body.get("session_id")
    except ValueError as e:
        return _error_json(400, str(e))
    except Exception:
        logger.exception("Error parsing request")
        return _error_json(400, "Invalid request")

    if requested_model and requested_model != model_name:
        return _error_json(400, f"Only configured model '{model_name}' is available")

    session_key = f"api:{session_id}" if session_id else API_SESSION_KEY
    session_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = request.app[
        "session_locks"
    ]
    # Audit (item 7 of the v0.0.7 second-pass review): the API used
    # to keep a regular ``dict`` of per-session locks, which grew
    # without bound — every new ``session_id`` (e.g. a UUID per
    # browser tab) leaked a Lock object.  We use a
    # ``WeakValueDictionary`` and a small factory so the lock is
    # strongly referenced only while the request is in flight.
    # Bug fix (audit 2026-07-18): a naive get/check/set had a TOCTOU
    # race — two concurrent requests for the same fresh session_id
    # could each create their own Lock, and the WVD would discard
    # one as soon as the request finished. We serialize creation on
    # a single application-wide init lock so each session_id maps
    # to exactly one Lock for its entire lifetime.
    init_lock: asyncio.Lock = request.app["session_locks_init"]
    async with init_lock:
        session_lock = session_locks.get(session_key)
        if session_lock is None:
            session_lock = asyncio.Lock()
            session_locks[session_key] = session_lock
    # Strong ref for the duration of this request so the WVD doesn't
    # GC the Lock between ``get`` and ``acquire``.
    _keep_alive = session_lock

    # Audit (B1 of the v0.0.8 third-pass review): the user message
    # used to land in the log verbatim, leaking API keys, tokens,
    # and other secrets the caller embedded in their request.
    # Apply ``scrub_text`` before logging — over-redaction is safe,
    # under-redaction is what we are guarding against.
    logger.info(
        "API request session_key={} text={} stream={}",
        session_key,
        scrub_text(text[:80]),
        stream,
    )
    # -- streaming path --
    if stream:
        resp = web.StreamResponse()
        resp.content_type = "text/event-stream"
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["Connection"] = "keep-alive"
        await resp.prepare(request)

        chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        stream_failed = False
        emitted_content = False

        async def _on_stream(token: str) -> None:
            nonlocal emitted_content
            if token:
                emitted_content = True
            await queue.put(token)

        async def _on_stream_end(*_a: Any, **_kw: Any) -> None:
            return None

        async def _run() -> None:
            nonlocal stream_failed
            try:
                async with session_lock:
                    response = await asyncio.wait_for(
                        agent_loop.process_direct(
                            content=text,
                            session_key=session_key,
                            channel="api",
                            chat_id=API_CHAT_ID,
                            on_stream=_on_stream,
                            on_stream_end=_on_stream_end,
                        ),
                        timeout=timeout_s,
                    )
                    if not emitted_content:
                        response_text = _response_text(response)
                        if response_text.strip():
                            await queue.put(response_text)
            except Exception:
                stream_failed = True
                logger.exception("Streaming error for session {}", session_key)
            finally:
                await queue.put(None)

        task = asyncio.create_task(_run())
        try:
            while True:
                token = await queue.get()
                if token is None:
                    break
                await resp.write(_sse_chunk(token, model_name, chunk_id))
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        if not stream_failed:
            await resp.write(_sse_chunk("", model_name, chunk_id, finish_reason="stop"))
            await resp.write(_SSE_DONE)
        return resp

    # -- non-streaming path --
    fallback = EMPTY_FINAL_RESPONSE_MESSAGE

    try:
        async with session_lock:
            try:
                response = await asyncio.wait_for(
                    agent_loop.process_direct(
                        content=text,
                        session_key=session_key,
                        channel="api",
                        chat_id=API_CHAT_ID,
                    ),
                    timeout=timeout_s,
                )
                response_text = _response_text(response)

                if not response_text or not response_text.strip():
                    logger.warning("Empty response for session {}, retrying", session_key)
                    retry_response = await asyncio.wait_for(
                        agent_loop.process_direct(
                            content=text,
                            session_key=session_key,
                            channel="api",
                            chat_id=API_CHAT_ID,
                        ),
                        timeout=timeout_s,
                    )
                    response_text = _response_text(retry_response)
                    if not response_text or not response_text.strip():
                        logger.warning("Empty response after retry, using fallback")
                        response_text = fallback

            except asyncio.TimeoutError:
                return _error_json(504, f"Request timed out after {timeout_s}s")
            except Exception:
                logger.exception("Error processing request for session {}", session_key)
                return _error_json(500, "Internal server error", err_type="server_error")
    except Exception:
        logger.exception("Unexpected API lock error for session {}", session_key)
        return _error_json(500, "Internal server error", err_type="server_error")

    return web.json_response(
        _chat_completion_response(
            response_text,
            model_name,
            # B3: forward the LLMResponse's usage dict.  ``getattr``
            # defends against older AgentRunResult variants that
            # don't have ``usage`` on the response.
            usage=getattr(response, "usage", None) or None,
        )
    )


async def handle_models(request: web.Request) -> web.Response:
    """GET /v1/models"""
    model_name = request.app.get("model_name", "Femtobot")
    return web.json_response(
        {
            "object": "list",
            "data": [
                {
                    "id": model_name,
                    "object": "model",
                    "created": 0,
                    "owned_by": "Femtobot",
                }
            ],
        }
    )


async def handle_health(request: web.Request) -> web.Response:
    """GET /health"""
    return web.json_response({"status": "ok"})


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    agent_loop, model_name: str = "Femtobot", request_timeout: float = 120.0
) -> web.Application:
    """Create the aiohttp application.

    Args:
        agent_loop: An initialized AgentLoop instance.
        model_name: Model name reported in responses.
        request_timeout: Per-request timeout in seconds.
    """
    app = web.Application()
    app["agent_loop"] = agent_loop
    app["model_name"] = model_name
    app["request_timeout"] = request_timeout
    # Per-session locks, keyed by session_key.  We use a
    # ``WeakValueDictionary`` so a session_id that no longer has a
    # request in flight doesn't keep the Lock alive indefinitely
    # (audit item 7 of the v0.0.7 second-pass review).  The request
    # handler holds a strong ref to the Lock for the duration of
    # the request to keep the WVD from GC'ing it mid-acquire.
    app["session_locks"] = weakref.WeakValueDictionary()
    # Init lock: serializes the get/check/set in handle_chat_completions
    # so concurrent requests for the same fresh session_id don't race
    # to create two Locks (audit 2026-07-18).
    app["session_locks_init"] = asyncio.Lock()

    # OpenAI-compatible endpoints
    app.router.add_post("/v1/chat/completions", handle_chat_completions)
    app.router.add_get("/v1/models", handle_models)
    app.router.add_get("/health", handle_health)

    return app
