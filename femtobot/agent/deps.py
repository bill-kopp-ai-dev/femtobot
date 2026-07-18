"""Runtime dependencies available to every tool.

When a tool is called, PydanticAI injects a RunContext whose ``deps``
attribute is the FemtobotDeps instance. Tools read the workspace,
session, security context, and other shared state from this object
instead of via module-level globals.

This file defines the dataclass. The FemtobotAgent factory is
responsible for building and binding a FemtobotDeps per turn.

Femtobot 1.0 (Phase 1) — this dataclass coexists with the legacy
``RequestContext`` in ``femtobot.agent.tools.context``. The legacy
type is removed in Phase 4 once ``FemtobotAgent`` becomes the
production agent loop.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from femtobot.agent.skills import SkillsLoader
    from femtobot.config.schema import Config
    from femtobot.security.workspace_access import WorkspaceScope
    from femtobot.session.manager import Session, SessionManager


@dataclass(slots=True)
class FemtobotDeps:
    """Shared state for one agent run."""

    config: "Config"
    workspace: Path
    session: "Session | None" = None
    session_manager: "SessionManager | None" = None
    skills: "SkillsLoader | None" = None
    workspace_scope: "WorkspaceScope | None" = None
    # Per-run metadata (timestamps, run id) — appended at the end.
    run_metadata: dict[str, str] = field(default_factory=dict)


__all__ = ["FemtobotDeps"]
