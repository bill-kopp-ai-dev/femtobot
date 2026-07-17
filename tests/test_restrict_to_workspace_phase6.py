"""Regression tests for Phase 6 of refactor-parity-with-nanobot.md.

R2-femtobot: the default of ``tools.restrictToWorkspace`` (Python
``restrict_to_workspace``) flipped from ``False`` to ``True`` so a fresh
instance constrains tool access to the workspace by default.  Existing
instances that explicitly set ``False`` are migrated to ``True`` by
``_migrate_config``.

These tests pin the contract:

1. A pydantic ``Config`` constructed from scratch resolves
   ``tools.restrict_to_workspace`` to ``True`` (the new default).
2. ``_migrate_config`` flips a legacy ``"restrictToWorkspace": False``
   to ``True``.
3. ``_migrate_config`` is a no-op when the field is already ``True``,
   and never turns ``False`` into ``False`` (avoids the migration
   racing with itself across reloads).
4. Loading the operator's ``.femtobot/config.json`` with the explicit
   ``False`` migrates it transparently, but re-saving the config leaves
   the operator's choice intact if they really want ``False``.
"""
from __future__ import annotations

from pathlib import Path

from femtobot.config.loader import _migrate_config, load_config
from femtobot.config.schema import Config


def test_default_restrict_to_workspace_is_true() -> None:
    """R2-femtobot: a freshly constructed ``Config()`` is workspace-restricted."""
    cfg = Config()
    assert cfg.tools.restrict_to_workspace is True, (
        "the default flipped to True in v0.2.0 (refactor-parity-with-nanobot.md Phase 6)"
    )


def test_migrate_flips_false_to_true() -> None:
    """R2-femtobot: legacy ``False`` becomes ``True`` after migration."""
    data = {"tools": {"restrictToWorkspace": False}}
    out = _migrate_config(data)
    assert out["tools"]["restrictToWorkspace"] is True, (
        "_migrate_config must promote restrictToWorkspace=False to True"
    )


def test_migrate_leaves_true_alone() -> None:
    """Migration is idempotent — already-True configs stay True."""
    data = {"tools": {"restrictToWorkspace": True}}
    out = _migrate_config(data)
    assert out["tools"]["restrictToWorkspace"] is True


def test_migrate_promotes_explicit_true_in_exec_subconfig() -> None:
    """R2-femtobot: ``tools.exec.restrictToWorkspace=False`` must also migrate."""
    data = {"tools": {"exec": {"restrictToWorkspace": False}}}
    out = _migrate_config(data)
    # The pre-existing move rule promotes the inner field to the outer tools config…
    assert out["tools"]["restrictToWorkspace"] is True, (
        "tools.exec.restrictToWorkspace=False must be promoted to the outer tools "
        "config AND flipped to True by the migration"
    )


def test_load_old_operator_config_flips_restrict_to_workspace(
    tmp_path: Path,
) -> None:
    """R2-femtobot: loading a legacy config with ``False`` yields ``True``."""
    config_file = tmp_path / "config.json"
    config_file.write_text(
        '{"tools": {"restrictToWorkspace": false}}', encoding="utf-8"
    )
    cfg = load_config(config_file)
    assert cfg.tools.restrict_to_workspace is True, (
        "legacy False must be migrated to True on load"
    )


def test_load_new_operator_config_keeps_true(
    tmp_path: Path,
) -> None:
    """R2-femtobot: a config that already says ``True`` stays ``True``."""
    config_file = tmp_path / "config.json"
    config_file.write_text(
        '{"tools": {"restrictToWorkspace": true}}', encoding="utf-8"
    )
    cfg = load_config(config_file)
    assert cfg.tools.restrict_to_workspace is True