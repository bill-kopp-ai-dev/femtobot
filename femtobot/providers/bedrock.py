"""AWS Bedrock provider using the Converse API (D1).

D1 (REFACTOR_PLAN.md Lote D): native integration with AWS Bedrock
via the standardized Converse API.  ``boto3`` is imported **lazily**
inside ``chat`` / ``chat_stream`` so a Femtobot install without
``boto3`` (the default) keeps working — only when a Bedrock provider
is actually constructed does ``boto3`` get loaded.

Two auth paths are supported:

1. **Standard SigV4 chain** via ``AWS_ACCESS_KEY_ID`` /
   ``AWS_SECRET_ACCESS_KEY`` / ``AWS_SESSION_TOKEN`` env vars (or
   the default boto3 credential provider chain — IAM role, SSO, etc.).
2. **Session-token shortcut** via ``BEDROCK_API_KEY`` for users who
   want to drop a single token in the Femtobot config.  We treat it
   as the ``aws_session_token`` and fall back to standard SigV4 if
   the standard env vars are also present.

The region defaults to ``BEDROCK_REGION`` or ``AWS_REGION`` or
``us-east-1``.  ``apiBase`` (when provided) is ignored — Bedrock
exposes a regional endpoint that the SDK resolves from the region.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from loguru import logger

from femtobot.providers.base import LLMProvider, LLMResponse


def _boto3():  # pragma: no cover - exercised indirectly via tests
    """Lazy import of :mod:`boto3` so the rest of the codebase stays import-clean.

    Raises ``ImportError`` with a clear remediation message when
    ``boto3`` is not installed.  Callers should install the optional
    extra ``femtobot[bedrock]`` (or ``pip install boto3``).
    """
    try:
        import boto3  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "AWS Bedrock provider requires boto3. Install it with "
            "`pip install boto3` (or `pip install femtobot[bedrock]`)."
        ) from exc
    return boto3


def _resolve_region(explicit: str | None = None) -> str:
    """Pick the AWS region from explicit arg → env → default ``us-east-1``."""
    if explicit:
        return explicit
    for var in ("BEDROCK_REGION", "AWS_REGION", "AWS_DEFAULT_REGION"):
        val = os.environ.get(var)
        if val:
            return val
    return "us-east-1"


def _build_runtime_options(api_key: str | None) -> dict[str, str]:
    """Apply the Bedrock-API-key shortcut to the runtime env.

    When ``BEDROCK_API_KEY`` (passed in as *api_key*) is set but the
    standard AWS_* env vars are not, we set the AWS access-key /
    secret to placeholder values and use the shortcut as the session
    token.  boto3 will then perform SigV4 with the placeholder creds
    plus the user-provided session token (this matches the AWS docs'
    "temporary credentials" flow).
    """
    if not api_key:
        return {}
    if os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"):
        # Standard chain is set — don't override.
        return {}
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "AKIA-FEMTOBOT-BEDROCK-SHORTCUT")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "femtobot-bedrock-shortcut-secret")
    os.environ["AWS_SESSION_TOKEN"] = api_key
    return {"AWS_SESSION_TOKEN": api_key}


class BedrockProvider(LLMProvider):
    """AWS Bedrock Converse API provider (D1).

    See module docstring for the auth paths.  ``model`` is the
    Bedrock model id (e.g. ``anthropic.claude-3-5-sonnet-20241022-v2:0``).
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,  # unused — kept for signature compatibility
        default_model: str = "anthropic.claude-3-5-sonnet-20241022-v2:0",
        region: str | None = None,
        **kwargs: Any,
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self._region = _resolve_region(region)
        # Apply BEDROCK_API_KEY shortcut env vars up front so boto3's
        # credential chain picks them up the moment the client is built.
        _build_runtime_options(api_key)
        # Lazy client construction: build on first call so that a Femtobot
        # install without boto3 doesn't crash at import time.
        self._client = None
        logger.debug(
            "Bedrock provider constructed (region={}, default_model={})",
            self._region,
            default_model,
        )

    def _get_client(self) -> Any:
        """Return the boto3 bedrock-runtime client, building it on demand (D1)."""
        if self._client is None:
            boto3 = _boto3()
            self._client = boto3.client(  # type: ignore[attr-defined]
                "bedrock-runtime",
                region_name=self._region,
            )
        return self._client

    def _converse_kwargs(self, **kwargs: Any) -> dict[str, Any]:
        """Translate Femtobot kwargs into a Bedrock ``converse`` payload (D1)."""
        # Map messages → bedrock messages array.
        # The AgentRunner's messages list uses OpenAI shape; we only
        # support user/assistant turns here (system is a separate field).
        messages: list[dict[str, Any]] = []
        system_parts: list[dict[str, Any]] = []
        for msg in kwargs.get("messages", []) or []:
            role = msg.get("role")
            if role == "system":
                # Bedrock Converse takes system as a top-level list.
                content = msg.get("content", "")
                if isinstance(content, str):
                    system_parts.append({"text": content})
                continue
            if role in ("user", "assistant"):
                content = msg.get("content", "")
                if isinstance(content, list):
                    blocks = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            blocks.append({"text": block.get("text", "")})
                    text = "\n".join(b.get("text", "") for b in blocks) or ""
                else:
                    text = str(content or "")
                messages.append({"role": role, "content": [{"text": text}]})
        out: dict[str, Any] = {"messages": messages}
        if system_parts:
            out["system"] = system_parts
        # Generation params.
        gen = kwargs.get("generation")
        max_tokens = (
            getattr(gen, "max_tokens", None) if gen else kwargs.get("max_tokens")
        ) or 4096
        out["inferenceConfig"] = {"maxTokens": int(max_tokens)}
        temperature = getattr(gen, "temperature", None) if gen else kwargs.get("temperature")
        if temperature is not None:
            out["inferenceConfig"]["temperature"] = float(temperature)
        return out

    async def chat(self, **kwargs: Any) -> LLMResponse:
        """Issue a non-streaming Converse call (D1)."""
        model = kwargs.get("model") or self.default_model
        payload = self._converse_kwargs(**kwargs)
        client = self._get_client()

        def _call() -> dict[str, Any]:
            return client.converse(modelId=model, **payload)

        result = await asyncio.to_thread(_call)
        text_blocks: list[str] = []
        for block in result.get("output", {}).get("message", {}).get("content", []):
            if isinstance(block, dict) and "text" in block:
                text_blocks.append(block["text"])
        text = "\n".join(text_blocks)
        usage: dict[str, int] = {}
        u = result.get("usage") or {}
        if u:
            usage = {
                "prompt_tokens": int(u.get("inputTokens", 0) or 0),
                "completion_tokens": int(u.get("outputTokens", 0) or 0),
                "total_tokens": int(u.get("totalTokens", 0) or 0),
            }
        return LLMResponse(
            content=text,
            finish_reason=result.get("stopReason", "stop") or "stop",
            usage=usage,
        )

    async def chat_stream(self, **kwargs: Any):  # pragma: no cover - streaming deferred
        """Streaming Converse is a follow-up; for now fall back to chat() (D1)."""
        return await self.chat(**kwargs)

    def get_default_model(self) -> str:
        return self.default_model
