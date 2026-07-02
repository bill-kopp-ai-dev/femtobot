"""Side-question handler for /btw.

Inspired by Claude Code's /btw feature:
``FEMTOBOT_CLI_REFACTOR_PLAN.md`` Camada 2, T2.4.

Behaviour
~~~~~~~~~~~
``/btw`` runs a read-only query against the current conversation context
without:
  - invoking any tools
  - modifying the session history
  - counting as a regular turn

The response is streamed inline in the terminal and discarded when the
session ends. It is purely ephemeral context from the LLM.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

from femtobot.bus.events import OutboundMessage


async def run_btw(
    loop: Any,
    question: str,
    session_key: str,
    channel: str = "cli",
    chat_id: str = "btw",
    on_stream: Any = None,
) -> OutboundMessage | None:
    """Run a /btw side-question and return the response.

    ``loop`` is the active ``AgentLoop`` instance.
    ``question`` is the text after ``/btw``.
    ``on_stream`` is an optional async callback ``(text: str)`` called for
    each streaming delta.

    Returns an ``OutboundMessage`` or ``None`` if the request fails.
    The message has ``metadata["_btw"] = True`` so callers can identify it.
    """
    t0 = time.monotonic()
    try:
        provider = getattr(loop, "provider", None)
        if provider is None:
            return None

        # Build a minimal context from the session's message history.
        session = None
        try:
            sessions = getattr(loop, "sessions", None)
            if sessions:
                session = sessions.get_or_create(session_key)
        except Exception:
            pass

        messages: list = []
        max_msgs = 10
        if session:
            try:
                cli_cfg = getattr(getattr(getattr(loop, "config", None), "agents", None) or {}, "cli", None) or {}
                btw_cfg = getattr(cli_cfg, "btw", None) or {}
                max_msgs = getattr(btw_cfg, "max_history_messages", 10)
                raw_hist = session.get_history(max_messages=max_msgs)
                if isinstance(raw_hist, list):
                    messages = raw_hist
            except Exception:
                pass

        logger.info("btw invoked", extra={
            "question_len": len(question),
            "history_len": len(messages) if isinstance(messages, list) else 0,
            "max_history": max_msgs,
        })

        # Append the /btw question as a user message (no tools allowed).
        messages.append({
            "role": "user",
            "content": (
                "Context: You are answering a side question. "
                "Do NOT use any tools. "
                "Answer briefly and directly from the conversation above.\n\n"
                f"Question: {question}"
            ),
        })

        # Call the provider directly with tools=None (no tool execution for /btw).
        gen = getattr(provider, "generate", None)
        if gen is None:
            return None

        async def _stream_cb(delta: str) -> None:
            if on_stream:
                try:
                    await on_stream(delta)
                except Exception:
                    pass

        result = await gen(
            messages=messages,
            tools=None,
            on_stream=_stream_cb,
        )

        content = ""
        if isinstance(result, dict):
            content = result.get("content", "")
        elif isinstance(result, str):
            content = result
        else:
            content = str(result) if result else ""

        elapsed = time.monotonic() - t0
        return OutboundMessage(
            channel=channel,
            chat_id=chat_id,
            content=content,
            metadata={
                "render_as": "text",
                "_btw": True,
                "_btw_elapsed_s": round(elapsed, 2),
            },
        )

    except Exception:
        return OutboundMessage(
            channel=channel,
            chat_id=chat_id,
            content="[btw] Failed to answer the question.",
            metadata={"render_as": "text", "_btw": True},
        )
