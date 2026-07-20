"""Adapter layer for the nanobot CLI mirror.

The mirror's ``commands.py`` is a verbatim copy of
``nanobot/cli/commands.py`` with ``s/nanobot/femtobot/g`` applied
to imports. That rename handles the 95% case — most ``nanobot.X``
imports map to femtobot symbols that exist at the same relative
path.

The ~5% that don't map mechanically land here as either:

  - **Aliens**: imports of femtobot symbols that exist but under a
    different name. We re-export them under their nanobot-shaped
    name (``nanobot.cli.stream.StreamRenderer`` →
    ``femtobot.cli._nanobot_mirror.stream.StreamRenderer``).

  - **Missing**: imports of femtobot symbols that **don't exist**
    (channels, cron, MCP UI, etc.). We provide a stub that raises
    a NotImplementedError when called, with a pointer at the
    femtobot docs.

This module exists so that ``commands.py`` (Phase 2) can be a
near-verbatim copy of nanobot's. Phase 5 may merge this back into
the mirror as a pure re-export module once the femtobot project
grows the missing functions naturally.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Phase 1 imports — only stream layer is mirrored. The other re-exports
# in this module (AgentLoop, MessageBus, Config, ... ) are populated in
# Phase 2 / Phase 3 as the commands.py mirror lands.

from femtobot.cli._nanobot_mirror.stream import (  # noqa: F401
    StreamRenderer,
    ThinkingSpinner,
    _make_console,
)


def optional_features():  # noqa: D401
    """nanobot's ``optional_features`` module re-export for the commands.py
    module-level ``from nanobot import optional_features as feature_support``.

    In nanobot this is a module that conditionally enables / disables
    optional integrations. In femtobot we provide a minimal stub that
    exposes no integrations; commands.py can still import ``feature_support``
    and read its attributes without raising.
    """
    return _OptionalFeatures()


class _OptionalFeatures:
    """Minimal stub matching the parts of ``nanobot.optional_features``
    that ``commands.py`` reads at module load time.

    Real implementations (``feature.foo()`` -> True/False) live behind the
    API; here we expose ``False`` for every feature flag so the parser
    keeps the disabled-by-default semantics. The femtobot project can
    flesh this out later by adding feature flags here.
    """

    def __getattr__(self, name: str) -> bool:  # pragma: no cover - trivial
        return False


feature_support = optional_features()


# ----- missing-from-femtobot stubs ---------------------------------------


class _MissingFemtobotFeature:
    """Common base for stub sub-apps that nanobot has but femtobot does not.

    Calling any method on these stubs raises NotImplementedError with a
    pointer at femtobot docs (CHANGELOG 0.1.0-cli.1 + open issues).
    """

    def __getattr__(self, name: str):  # pragma: no cover - only on call
        def _missing(*args, **kwargs):
            raise NotImplementedError(
                f"femtobot does not yet ship a CLI sub-app / feature "
                f"matching nanobot's `{name}`. See CHANGELOG.md "
                f"0.1.0-cli.1 and the open issues for the roadmap."
            )

        return _missing


def create_gateway_app(*args, **kwargs):
    """``nanobot.cli.gateway.create_gateway_app`` re-export.

    femtobot does not currently ship a gateway (textual/web UI) command;
    keep the symbol so the module imports cleanly, but raise on call.
    """
    raise NotImplementedError(
        "femtobot does not yet ship the gateway command. See CHANGELOG.md."
    )


def run_onboard(*args, **kwargs):
    """``nanobot.cli.onboard.run_onboard`` re-export stub."""
    raise NotImplementedError(
        "femtobot CLI does not yet bundle run_onboard; use `femtobot config`."
    )


def run_quick_start_onboard(*args, **kwargs):
    """``nanobot.cli.onboard.run_quick_start_onboard`` re-export stub."""
    raise NotImplementedError(
        "femtobot CLI does not yet bundle run_quick_start_onboard."
    )


# ----- nanobot / femtobot logo + version helpers ------------------------

# ``commands.py`` references these via ``from nanobot import __logo__,
# __version__`` which is OK because the ``s/nanobot/femtobot/g`` rename
# turns them into ``from femtobot import __logo__, __version__``.
# We just sanity-import above; nothing else needed here.

# ----- femtobot-only config helpers used by Phase 2 -----------------------

# These mirror the nanobot config loader helpers so that Phase 2's
# commands.py can import them under femtobot. We re-export where they
# already exist, and provide thin placeholders where they don't.

try:
    from femtobot.config.loader import (  # noqa: F401
        get_config_path,
        load_config,
        save_config,
        set_config_path,
        resolve_config_env_vars,
        merge_missing_defaults,
    )
except ImportError:  # pragma: no cover - femtobot config loader may be elsewhere
    # If femtobot does not have a loader with this exact signature, we
    # fake a minimal one so the mirror imports cleanly. The real
    # config-loading logic still flows through ``Config(...)``.
    def get_config_path() -> Path:
        return Path.home() / ".femtobot" / "config.json"

    def load_config(*args, **kwargs) -> Config:
        return Config(*args, **kwargs)

    def save_config(*_args, **_kwargs):
        raise NotImplementedError("femtobot.save_config not implemented")

    def set_config_path(*_args, **_kwargs):
        raise NotImplementedError("femtobot.set_config_path not implemented")

    def resolve_config_env_vars(cfg):
        return cfg

    def merge_missing_defaults(cfg):
        return cfg


# ----- entry points re-exported by femtobot.cli.__init__ ----------------

# These are added in Phase 2 when commands.py is copied. They live here
# only so Phase 1 can wire the ``_nanobot_mirror.__init__`` exports.
# Stub them for now.

agent_app = _MissingFemtobotFeature()
gateway_app = _MissingFemtobotFeature()
sessions_app = _MissingFemtobotFeature()
mcp_app = _MissingFemtobotFeature()
femtobot_app = _MissingFemtobotFeature()


def version_callback(*_args, **_kwargs):  # pragma: no cover - stub
    sys.stderr.write("femtobot (mirror placeholder — see Phase 2)\n")


async def run_interactive_async(*_args, **_kwargs):  # pragma: no cover - stub
    raise NotImplementedError(
        "run_interactive_async is added by the commands.py mirror in Phase 2."
    )
