"""Regression tests for ``create_instance_readme``.

R2-femtobot (refactor-parity-with-nanobot.md) review: after the
``--suffix`` flag was dropped from ``onboard``, the ``README.md``
template emitted by ``create_instance_readme`` still referenced
``{suffix or "default"}`` inside an f-string, but the function no
longer accepted a ``suffix`` parameter.  Calling ``onboard`` therefore
raised ``NameError: name 'suffix' is not defined`` at runtime.

These tests pin the new contract:

1. ``create_instance_readme`` runs without NameError on a fresh dir.
2. The emitted README does not mention ``--suffix``.
3. The emitted README documents the legitimate entry points
   (``femtobot status``, ``femtobot agent``) and points at
   ``--folder-path`` / ``FEMTOBOT_HOME`` for multi-instance setups.
4. ``create_instance_readme`` is idempotent: a second call does not
   overwrite an existing user-edited README.
"""

from __future__ import annotations

from pathlib import Path

from femtobot.utils.helpers import create_instance_readme


def test_create_instance_readme_does_not_raise(tmp_path: Path) -> None:
    """Regression: must not raise ``NameError: name 'suffix' is not defined``."""
    create_instance_readme(tmp_path)
    readme = tmp_path / "README.md"
    assert readme.exists(), "README.md must be created"


def test_readme_does_not_reference_suffix_flag(tmp_path: Path) -> None:
    """R2: the ``--suffix`` flag is gone; the README must not advertise it."""
    create_instance_readme(tmp_path)
    body = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "--suffix" not in body, (
        "README.md still mentions --suffix; this flag was removed in v0.2.0"
    )


def test_readme_documents_legacy_entry_points(tmp_path: Path) -> None:
    """R2: the README should teach the operator how to use the instance."""
    create_instance_readme(tmp_path)
    body = (tmp_path / "README.md").read_text(encoding="utf-8")
    # Direct commands
    assert "femtobot status" in body
    assert "femtobot agent" in body
    # Multi-instance pointer
    assert "--folder-path" in body or "FEMTOBOT_HOME" in body


def test_readme_is_idempotent(tmp_path: Path) -> None:
    """R2: existing user-edited README must be preserved (sync semantics)."""
    readme = tmp_path / "README.md"
    sentinel = "# my hand-written README\n\ndo not touch\n"
    readme.write_text(sentinel, encoding="utf-8")

    create_instance_readme(tmp_path)

    assert readme.read_text(encoding="utf-8") == sentinel, (
        "create_instance_readme overwrote a user-edited README.md"
    )