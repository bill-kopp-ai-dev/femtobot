"""Logfire setup for Femtobot.

Logfire is OPT-IN. By default nothing is sent. Set FEMTOBOT_LOGFIRE=1
or call configure(send_to_logfire="if-token-present") to enable.

Typical usage:

    from femtobot.observability import logfire_setup
    logfire_setup.configure_if_enabled()  # respects FEMTOBOT_LOGFIRE
    logfire_setup.instrument_pydantic_ai()  # safe to call once at startup
"""
from __future__ import annotations

import os
from typing import Literal

import logfire

_CONFIGURED = False
_INSTRUMENTED = False
_HTTPX_INSTRUMENTED = False

SendMode = Literal["yes", "no", "if-token-present"]


def _resolve_send_mode() -> SendMode:
    """Read the send-to-logfire mode from env.

    Precedence:
      1. FEMTOBOT_LOGFIRE_SEND=auto|yes|no   (explicit)
      2. FEMTOBOT_LOGFIRE=1  -> yes, otherwise no
      3. Default: if-token-present (auto)
    """
    explicit = os.environ.get("FEMTOBOT_LOGFIRE_SEND", "").lower()
    if explicit in ("auto", "if-token-present"):
        return "if-token-present"
    if explicit in ("yes", "1", "true", "on"):
        return "yes"
    if explicit in ("no", "0", "false", "off"):
        return "no"
    if os.environ.get("FEMTOBOT_LOGFIRE") in ("1", "true", "yes"):
        return "yes"
    return "if-token-present"


def configure(*, send_to_logfire: bool | SendMode | None = None) -> None:
    """Configure the Logfire SDK.

    Args:
        send_to_logfire:
            - True / "yes" → always send (requires write token).
            - False / "no" → never send (OTel collector only).
            - None / "if-token-present" → auto-detect from env.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    mode = send_to_logfire if send_to_logfire is not None else _resolve_send_mode()
    if mode is True or mode == "yes":
        logfire.configure(send_to_logfire=True)
    elif mode is False or mode == "no":
        logfire.configure(send_to_logfire=False)
    else:
        logfire.configure(send_to_logfire="if-token-present")
    _CONFIGURED = True


def instrument_pydantic_ai() -> None:
    """Instrument PydanticAI agent runs. Call once at process startup."""
    global _INSTRUMENTED
    if _INSTRUMENTED:
        return
    logfire.instrument_pydantic_ai()
    _INSTRUMENTED = True


def instrument_httpx() -> None:
    """Instrument httpx HTTP traffic. Opt-in via ``FEMTOBOT_LOGFIRE_HTTPX=1``.

    Captures every outgoing HTTP request (including the model provider
    traffic that PydanticAI sends through httpx). Off by default
    because the volume of spans is high.
    """
    global _HTTPX_INSTRUMENTED
    if _HTTPX_INSTRUMENTED:
        return
    if os.environ.get("FEMTOBOT_LOGFIRE_HTTPX") not in ("1", "true", "yes", "on"):
        return
    logfire.instrument_httpx(capture_all=True)
    _HTTPX_INSTRUMENTED = True


def configure_if_enabled() -> None:
    """Configure Logfire only if FEMTOBOT_LOGFIRE=1 or token is present."""
    configure()


__all__ = [
    "configure",
    "configure_if_enabled",
    "instrument_pydantic_ai",
    "instrument_httpx",
]
