"""Tests for Camada 3 T3.1 textual_app lazy loading."""
from __future__ import annotations

import sys

import pytest

import femtobot.cli.textual_app as _tmod

_TEXTUAL_AVAILABLE = _tmod._TEXTUAL_AVAILABLE


def test_textual_app_imports_without_crashing():
    """Module import must not raise, even if textual is absent."""
    import femtobot.cli.textual_app as mod
    assert mod is not None


def test_textual_not_available_is_runtime_error():
    """TextualNotAvailable must inherit RuntimeError for compatibility."""
    from femtobot.cli.textual_app import TextualNotAvailable
    assert issubclass(TextualNotAvailable, RuntimeError)


def test_textual_not_available_carries_message():
    """TextualNotAvailable can be raised with an informative message."""
    from femtobot.cli.textual_app import TextualNotAvailable
    err = TextualNotAvailable("pip install textual")
    assert "textual" in str(err)


def test_textual_availability_flag_is_bool():
    """Module exposes _TEXTUAL_AVAILABLE as a proper bool."""
    import femtobot.cli.textual_app as mod
    assert hasattr(mod, "_TEXTUAL_AVAILABLE")
    assert isinstance(mod._TEXTUAL_AVAILABLE, bool)


@pytest.mark.skipif(_TEXTUAL_AVAILABLE, reason="textual is installed; app would not raise")
def test_constructing_without_textual_raises_useful_error():
    """FemtobotTextualApp() must raise TextualNotAvailable, not AttributeError."""
    from femtobot.cli.textual_app import FemtobotTextualApp, TextualNotAvailable
    with pytest.raises(TextualNotAvailable) as exc_info:
        FemtobotTextualApp()
    msg = str(exc_info.value).lower()
    assert "textual" in msg
    assert "install" in msg


@pytest.mark.skipif(_TEXTUAL_AVAILABLE, reason="textual is installed; stubs are not defined")
def test_tstub_is_instantiable_without_textual():
    """When textual is absent, _TStub must be instantiable (no crash)."""
    import femtobot.cli.textual_app as mod
    stub = mod._TStub()
    assert stub is not None


def test_textual_app_does_not_eagerly_load_textual():
    """Importing textual_app must not pull in the textual package as a side-effect."""
    had_textual = "textual" in sys.modules
    import femtobot.cli.textual_app  # noqa: F401
    if not had_textual:
        assert "textual" not in sys.modules, (
            "Importing textual_app loaded 'textual' eagerly — import must stay lazy"
        )
