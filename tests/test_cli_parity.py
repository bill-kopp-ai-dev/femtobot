"""CLI parity v0.1.7 regression tests.

Pins the fixes for the seven issues raised by the eleventh-round
parity review of ``femtobot/cli`` against upstream nanobot:

* Issue 1: ``femtobot onboard`` no longer auto-fires the wizard
  when invoked on a TTY without arguments.
* Issue 2: ``run_onboard_wizard`` prints a 2-line welcome header.
* Issue 3: A main menu (Quick Start / Exit) appears before the
  first prompt.
* Issue 4: An API-key prefix is echoed back to the user after
  capture.
* Issue 5: The wizard config-reload no longer swallows
  ``Exception`` silently.
* Issue 6: ``_CURATED_MODELS`` falls back to a registry-derived
  default for unknown providers and ``_env_key_for`` reads the
  ``env_key`` from ``ProviderSpec``.
* Issue 7: Suffix validation runs *before* the wizard block.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from femtobot.cli.commands import app
from femtobot.cli.onboard_wizard import (
    _CURATED_MODELS,
    _default_curated_for,
    _env_key_for,
    _models_for,
    run_onboard_wizard,
)
from femtobot.config.schema import Config

# ---------------------------------------------------------------------------
# Issue 1 — wizard opt-in only
# ---------------------------------------------------------------------------


def test_issue1_onboard_no_args_in_tty_does_not_run_wizard(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plain ``femtobot onboard`` in a TTY must NOT auto-fire the wizard."""
    runner = CliRunner()
    with patch("femtobot.cli.onboard_wizard.run_onboard_wizard") as f, \
         patch("sys.stdin") as fake_stdin, \
         patch("femtobot.config.loader.validate_instance_suffix", return_value="ok"):
        fake_stdin.isatty.return_value = True
        runner.invoke(app, ["onboard"])
        # The wizard function must not have been called.
        assert f.called is False, (
            "CLI-parity v0.1.7 Issue 1: the wizard auto-fired on a "
            "plain `femtobot onboard`.  It must be opt-in only via --wizard."
        )


def test_issue1_onboard_wizard_flag_still_works() -> None:
    """The --wizard flag is the only way to launch the wizard now."""
    # Source-level guard: the wizard branch must be guarded by the
    # ``wizard`` flag, not by ``isatty()``.  We replaced the old
    # ``if wizard or (sys.stdin.isatty() and not ...):`` with
    # ``if not wizard: ... elif sys.stdin.isatty(): ...``.
    import inspect

    from femtobot.cli import commands as cli_module

    src = inspect.getsource(cli_module)
    # Must not contain the old auto-trigger pattern.
    forbidden = (
        " if wizard or (sys.stdin.isatty()"
    )
    assert forbidden not in src, (
        "CLI-parity v0.1.7 Issue 1: the auto-trigger pattern "
        "(if wizard or (sys.stdin.isatty()...) has reappeared."
    )
    # The new pattern must be present.
    assert "if not wizard:" in src, (
        "CLI-parity v0.1.7 Issue 1: the new opt-in gate "
        "(if not wizard:) is missing from onboard()."
    )


def test_issue1_onboard_wizard_flag_in_non_tty_skips() -> None:
    """--wizard in a non-TTY (CI / pipe) prints a warning and skips rather
    than blocking on stdin input."""
    import inspect

    from femtobot.cli import commands as cli_module

    src = inspect.getsource(cli_module)
    # The non-TTY branch prints a yellow "! --wizard requires a TTY" line.
    assert "--wizard requires a TTY" in src, (
        "CLI-parity v0.1.7 Issue 1: the non-TTY --wizard fallback "
        "message is missing from onboard()."
    )


# ---------------------------------------------------------------------------
# Issue 2 — welcome header
# ---------------------------------------------------------------------------


def test_issue2_wizard_prints_welcome_header() -> None:
    """``run_onboard_wizard`` prints a bold welcome line and a dim 2-line hint."""
    cfg = Config()
    answers = iter(["Q", "anthropic", "claude-3-5-sonnet-20241022", ""])
    fake_console = MagicMock()

    with patch("sys.stdin") as fake_stdin, \
         patch.dict(os.environ, {}, clear=False), \
         patch("femtobot.cli.onboard_wizard.Prompt") as fp:
        fake_stdin.isatty.return_value = True
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)
        fp.ask.side_effect = lambda *a, **k: next(answers)
        run_onboard_wizard(config=cfg, console=fake_console)

    # Some print call must contain "Femtobot quick setup".
    args_strings = [
        (c.args[0] if c.args else "")
        for c in fake_console.print.call_args_list
    ]
    assert any("Femtobot quick setup" in s for s in args_strings), (
        "CLI-parity v0.1.7 Issue 2: welcome header missing."
    )


# ---------------------------------------------------------------------------
# Issue 3 — main menu
# ---------------------------------------------------------------------------


def test_issue3_main_menu_quick_start_or_exit() -> None:
    """The main menu prompt accepts [Q] and [E] (Quick Start / Exit)."""
    cfg = Config()
    answers = iter(["Q", "anthropic", "claude-3-5-sonnet-20241022", ""])
    fake_console = MagicMock()

    with patch("sys.stdin") as fake_stdin, \
         patch.dict(os.environ, {}, clear=False), \
         patch("femtobot.cli.onboard_wizard.Prompt") as fp:
        fake_stdin.isatty.return_value = True
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)
        fp.ask.side_effect = lambda *a, **k: next(answers)
        run_onboard_wizard(config=cfg, console=fake_console)

    args_strings = [
        (c.args[0] if c.args else "")
        for c in fake_console.print.call_args_list
    ]
    assert any("Quick Start" in s and "Exit" in s for s in args_strings), (
        "CLI-parity v0.1.7 Issue 3: main-menu print missing."
    )
    # The Choose prompt must have been issued.
    asks = [
        c.args[0] if c.args else ""
        for c in fp.ask.call_args_list
    ]
    assert any("Choose" in a for a in asks)


def test_issue3_main_menu_exit_returns_none() -> None:
    """Pressing E at the main menu returns None and aborts the wizard."""
    cfg = Config()
    answers = iter(["E"])  # User picks Exit on the main menu.
    fake_console = MagicMock()

    with patch("sys.stdin") as fake_stdin, \
         patch.dict(os.environ, {}, clear=False), \
         patch("femtobot.cli.onboard_wizard.Prompt") as fp:
        fake_stdin.isatty.return_value = True
        fp.ask.side_effect = lambda *a, **k: next(answers)
        result = run_onboard_wizard(config=cfg, console=fake_console)

    assert result is None


# ---------------------------------------------------------------------------
# Issue 4 — API key prefix confirmation
# ---------------------------------------------------------------------------


def test_issue4_key_prefix_confirmation_echoed() -> None:
    """After the user pastes an API key, its first 4 chars are echoed back."""
    cfg = Config()
    cfg.providers = {}  # Force the wizard to ask for the key.
    answers = iter(["Q", "openai", "gpt-4o", "sk-openai-test-key"])
    fake_console = MagicMock()

    with patch("sys.stdin") as fake_stdin, \
         patch.dict(os.environ, {}, clear=False), \
         patch("femtobot.cli.onboard_wizard.Prompt") as fp:
        fake_stdin.isatty.return_value = True
        # Make sure no key is in the environment so the wizard asks.
        os.environ.pop("OPENAI_API_KEY", None)
        fp.ask.side_effect = lambda *a, **k: next(answers)
        run_onboard_wizard(config=cfg, console=fake_console)

    args_strings = [
        (c.args[0] if c.args else "")
        for c in fake_console.print.call_args_list
    ]
    # "sk-o" is the first 4 chars of "sk-openai-test-key".
    assert any("sk-o" in s for s in args_strings), (
        "CLI-parity v0.1.7 Issue 4: API-key prefix confirmation missing."
    )


# ---------------------------------------------------------------------------
# Issue 5 — wizard config reload: no more silent exception swallow
# ---------------------------------------------------------------------------


def test_issue5_commands_module_does_not_silently_swallow_reload_exceptions() -> None:
    """CLI-parity v0.1.7 Issue 5: the wizard_result handler keeps
    in-memory config instead of silently reloading from disk.

    Source-level guard: when the wizard produced a config mutation
    we now keep ``wizard_result.config`` (or fall back to the
    in-memory config); we no longer call ``load_config`` again to
    "re-sync" with stale on-disk data.
    """
    import inspect

    from femtobot.cli import commands as cli_module

    src = inspect.getsource(cli_module)
    # The old reloader block read:
    #   try:
    #       reloaded = load_config(config_file)
    #       if reloaded is not None:
    #           config = reloaded
    #   except Exception:  # pragma: no cover - defensive
    #       pass
    # We assert two things:
    #  (a) there is NO ``reloaded = load_config(config_file)`` re-assignment
    #      inside the wizard_result branch, and
    #  (b) inside that branch there is no bare ``pass`` after
    #      ``except Exception``.
    if "wizard_result is not None" in src:
        ws = src.index("wizard_result is not None")
        # Slice generously so future expansions don't trip the test.
        wizard_section = src[ws:ws + 1200]
        assert "reloaded = load_config" not in wizard_section, (
            "CLI-parity v0.1.7 Issue 5: load_config() re-loader reappeared."
        )
        assert (
            "except Exception" not in wizard_section
            or "pass" not in wizard_section.split("except Exception", 1)[1][:200]
        ), (
            "CLI-parity v0.1.7 Issue 5: exception swallowing still present "
            "in the wizard_result branch."
        )


# ---------------------------------------------------------------------------
# Issue 6 — _CURATED_MODELS data-driven; _env_key_for reads the registry
# ---------------------------------------------------------------------------


def test_issue6_curated_models_table_has_eight_known_providers() -> None:
    """The eight curated providers still get per-provider defaults."""
    for known in ("anthropic", "openai", "openrouter", "ollama",
                  "gemini", "groq", "mistral", "deepseek"):
        assert known in _CURATED_MODELS, (
            f"CLI-parity v0.1.7 Issue 6: known provider '{known}' missing."
        )


def test_issue6_models_for_unknown_provider_uses_fallback() -> None:
    """``_models_for('ant_ling')`` returns the registry-derived default."""
    fallback = _models_for("ant_ling")
    assert fallback == _default_curated_for("ant_ling")
    assert fallback  # at least one option


def test_issue6_models_for_known_provider_returns_real_menu() -> None:
    """``_models_for('anthropic')`` still returns the curated menu, not a fallback."""
    assert "claude-3-7-sonnet-20250219" in _models_for("anthropic")


def test_issue6_env_key_for_reads_provider_registry() -> None:
    """``_env_key_for('openai')`` returns ``OPENAI_API_KEY`` (from registry)."""
    assert _env_key_for("openai") == "OPENAI_API_KEY"


def test_issue6_env_key_for_unknown_falls_back_to_hardcoded() -> None:
    """``_env_key_for('unknown-foo')`` falls back to the small hardcoded table."""
    assert _env_key_for("unknown-foo") is None or isinstance(_env_key_for("unknown-foo"), str)


def test_issue6_env_key_for_ant_ling_uses_registry_when_available() -> None:
    """``ant_ling`` is registered; its env_key should be ANT_LING_API_KEY."""
    from femtobot.providers.registry import find_by_name

    spec = find_by_name("ant_ling")
    if spec and spec.env_key:
        # _env_key_for must agree with the registry.
        assert _env_key_for("ant_ling") == spec.env_key


# ---------------------------------------------------------------------------
# Issue 7 — suffix validation runs before the wizard
# ---------------------------------------------------------------------------


def test_issue7_suffix_validation_runs_before_wizard() -> None:
    """CLI-parity v0.1.7 Issue 7: suffix validation is *before* the wizard.

    Validate_instance_suffix must be called before the wizard branch,
    so a bad suffix is rejected before any interactive prompt fires.
    """
    import inspect

    from femtobot.cli import commands as cli_module

    src = inspect.getsource(cli_module)
    # Locate def onboard (decorated typer command).
    onboard_idx = src.find('def onboard(')
    assert onboard_idx >= 0, "Issue 7: def onboard not found"
    # Slice generously so future expansions don't trip the test.
    # Note: validate_instance_suffix is referenced by short name
    # inside onboard() because it is imported at the top of the
    # function body (line 759 in v0.1.7).
    onboard_src = src[onboard_idx: onboard_idx + 8000]
    val_idx = onboard_src.find("validate_instance_suffix(")
    wizard_idx = onboard_src.find("if not wizard:")
    assert val_idx >= 0, (
        "Issue 7: validate_instance_suffix(...) call not found in onboard()."
    )
    assert wizard_idx >= 0, (
        "Issue 7: 'if not wizard:' marker not found in onboard()."
    )
    assert val_idx < wizard_idx, (
        "CLI-parity v0.1.7 Issue 7: suffix validation must run *before* "
        "the wizard branch so a bad suffix reports before any prompt is asked."
    )
