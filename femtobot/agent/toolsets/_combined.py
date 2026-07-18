"""Combined toolset aggregator for FemtobotAgent.

Femtobot 1.0 (Phase 3) — gathers every toolset module under
``femtobot.agent.toolsets`` and exposes a single ``combined_toolset()``
function. Each module declares a ``toolset() -> list[Tool]`` callable.

Migration status (Phase 3):
- ``femtobot_timer`` migrated as the Phase 1 pilot.
- 21 remaining legacy tools (``self``, ``my``, ``message``, ``find_files``,
  ``grep``, ``read_file``, ``write_file``, ``apply_patch``, ``exec``,
  ``exec_session``, ``web_search``, ``web_fetch``, ``image_generation``,
  ``mcp``, and the 8 misc helpers) are still served by the legacy
  ``AgentLoop`` via ``femtobot/agent/tools/*.py``.

Full migration of those tools is deferred: each legacy tool relies on
``current_tool_workspace()`` / ``RequestContext`` globals that the
PydanticAI adapter does not yet expose. Until a parallel
``FemtobotDeps`` shim is built for those globals, ``combined_toolset()``
returns only the pilots that already migrated cleanly.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from femtobot.config.schema import Config


def _available_toolsets() -> list[Any]:
    """Return all migrated toolset modules.

    Each entry is a module with a ``toolset() -> list[Tool]`` callable.
    New migrations append their module here. Modules that fail to
    import are skipped (defensive — keeps the import surface small).
    """
    candidates: list[tuple[str, str]] = [
        ("femtobot.agent.toolsets.femtobot_timer", "toolset"),
    ]
    out: list[Any] = []
    for module_path, attr in candidates:
        try:
            import importlib

            mod = importlib.import_module(module_path)
        except Exception as exc:
            # Bug fix (re-audit 2026-07-18): log the failure rather
            # than swallowing it silently — otherwise a regression
            # in any toolset shows up as "tool mysteriously missing"
            # with zero diagnostic.
            logger.warning(
                "Failed to import toolset candidate {}: {}", module_path, exc
            )
            continue
        func = getattr(mod, attr, None)
        if func is None:
            continue
        out.append(func)
    return out


def combined_toolset(config: "Config | None" = None) -> list[Any]:
    """Aggregate every available toolset into one list of PydanticAI Tools.

    Args:
        config: Active Femtobot config. Reserved for future filtering
            (``config.tools.<name>.enabled``). Currently unused — the
            legacy ``AgentLoop`` still owns enable/disable semantics.
    """
    del config  # Reserved for Phase 4 / per-tool enable filter.
    tools: list[Any] = []
    for toolset_fn in _available_toolsets():
        try:
            tools.extend(toolset_fn())
        except Exception as exc:
            # Bug fix (re-audit 2026-07-18): log per-toolset failures
            # instead of silently skipping. A failing toolset must not
            # block the rest of the agent, but the regression should
            # be visible in the operator's logs.
            logger.warning(
                "Toolset {} failed to build: {}",
                getattr(toolset_fn, "__module__", toolset_fn),
                exc,
            )
            continue
    return tools


__all__ = ["combined_toolset"]
