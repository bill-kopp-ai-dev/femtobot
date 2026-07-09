"""Kill-switch for ``!`...``` inline shell substitution in skill bodies (B1+).

The ``_run_bash_inlines`` helper runs a real shell with
``shell=True`` — the feature is *meant* to be a shell.  A
skill-body that has been tampered with, however, can use that as a
code-execution channel.  Operators can opt out globally by setting
``FEMTOBOT_NO_BASH_INLINE=1``; the env var takes precedence over
the caller and replaces the inline command with a placeholder so
``shell=True`` is never reached.
"""

from __future__ import annotations

import subprocess

import pytest

from femtobot.cli.md_commands import _run_bash_inlines


def _assert_subprocess_never_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wire a sentinel on ``subprocess.run`` that fails the test if used."""

    def _explode(*args: object, **kwargs: object) -> object:  # pragma: no cover
        raise AssertionError(
            "subprocess.run was called but the kill-switch should have "
            "prevented shell execution"
        )

    monkeypatch.setattr(subprocess, "run", _explode)


def test_kill_switch_env_var_disables_inline_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B1+ security: ``FEMTOBOT_NO_BASH_INLINE=1`` blocks ``subprocess.run`` (B1+)."""
    monkeypatch.setenv("FEMTOBOT_NO_BASH_INLINE", "1")
    _assert_subprocess_never_called(monkeypatch)

    result = _run_bash_inlines("Inline: !`rm -rf /`")
    # The exact inline command must NOT appear in the output (only
    # the placeholder prefix), and the sentinel must not have fired.
    assert "rm -rf /" in result  # the cmd is in the placeholder text
    assert result.startswith("Inline: [bash disabled:")


def test_kill_switch_kwarg_value_does_not_matter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B1+: any non-empty value (``"true"``, ``"yes"``, ``"0"``, ...) disables it."""
    monkeypatch.setenv("FEMTOBOT_NO_BASH_INLINE", "true")
    _assert_subprocess_never_called(monkeypatch)
    result = _run_bash_inlines("X: !`echo hi`")
    assert "bash disabled" in result


def test_kill_switch_unset_uses_normal_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """B1+: without the env var, ``subprocess.run`` is invoked (B1+)."""
    monkeypatch.delenv("FEMTOBOT_NO_BASH_INLINE", raising=False)

    calls: list[object] = []

    def _fake_run(cmd: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        # echo the command itself so we can verify both ran.
        return subprocess.CompletedProcess(
            args=str(cmd), returncode=0, stdout=f"{cmd}\n", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)

    result = _run_bash_inlines("X:!`echo hi`,!`echo there`")
    # Two inline calls were dispatched to subprocess.run.
    assert len(calls) == 2
    # Both stdout values were substituted in.
    assert "X:echo hi,echo there" == result
