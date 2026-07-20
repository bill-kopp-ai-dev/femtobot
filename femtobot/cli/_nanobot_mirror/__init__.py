"""Mirror of the nanobot CLI for the femtobot package.

The CLI module is borrowed from ``nanobot`` (project sibling) and
adapted to use femtobot's bus, agent loop, and config. The full
mirror lives here so that downstream consumers can either import
the names directly (``from femtobot.cli._nanobot_mirror import
StreamRenderer``) or re-export them via ``femtobot.cli``.

Removed (parity-only, not present in nanobot):
  - ParityStreamRenderer
  - SpinnerWithElapsed
  - render_header_bar / render_welcome_card
  - ui_parity=compat profile

Added (femtobot-specific):
  - femtobot_provider_minimax: thin OpenAI-compat provider.
  - _ui_parity_shim.deprecation: hard-error (exit 64) on ``--ui compat``.
"""

from femtobot.cli._nanobot_mirror._adapters import (
    agent_app,
    femtobot_app,
    gateway_app,
    sessions_app,
    mcp_app,
    version_callback,
    run_interactive_async,
)
from femtobot.cli._nanobot_mirror.stream import (
    StreamRenderer,
    ThinkingSpinner,
    _make_console,
)

__all__ = [
    "StreamRenderer",
    "ThinkingSpinner",
    "_make_console",
    "femtobot_app",
    "agent_app",
    "gateway_app",
    "sessions_app",
    "mcp_app",
    "version_callback",
    "run_interactive_async",
]
