"""Pairing module stub for Femtobot.

This module provides stub implementations to maintain compatibility
with code that expects pairing functionality. In Femtobot's CLI-first
architecture, pairing/approval is not required.
"""

# Metadata keys used by channels and commands to tag pairing-related messages.
PAIRING_CODE_META_KEY = "_pairing_code"
PAIRING_COMMAND_META_KEY = "_pairing_command"


def format_pairing_reply(code: str, expiry_seconds: int | None = None) -> str:
    """Stub: Return a formatted pairing reply message."""
    return f"Pairing code: {code}"


def generate_code() -> str:
    """Stub: Generate a random pairing code."""
    import uuid

    return uuid.uuid4().hex[:8].upper()


def is_approved(sender_id: str) -> bool:
    """Stub: Always return True - approval is not required in CLI-first mode."""
    return True


__all__ = [
    "PAIRING_CODE_META_KEY",
    "PAIRING_COMMAND_META_KEY",
    "format_pairing_reply",
    "generate_code",
    "is_approved",
]
