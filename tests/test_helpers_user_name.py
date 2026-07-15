"""Tests for the user.name placeholder added in T13 (ui-parity Q2).

The ``build_default_onboard_config`` template must seed
``agents.defaults.user.name`` with the ``<your-name>`` sentinel so the
parity header bar / welcome card know where to interpolate the human
operator's name. The sentinel is replaced at render time by
``cli/parity_stream.py::resolve_user_name``.
"""

from __future__ import annotations


def test_onboard_config_seeds_user_name_placeholder(tmp_path):
    from femtobot.utils.helpers import build_default_onboard_config

    cfg = build_default_onboard_config(tmp_path)
    assert cfg.agents.defaults.user.name == "<your-name>"


def test_onboard_config_user_name_serializes_into_json(tmp_path):
    """Sanity: the field is wired into the dump pipeline, so a fresh
    ``config.json`` produced from this Config carries the key on disk."""
    import json

    from femtobot.utils.helpers import build_default_onboard_config, write_default_config

    cfg = build_default_onboard_config(tmp_path)
    out = tmp_path / "config.json"
    write_default_config(cfg, out, force=True)
    data = json.loads(out.read_text(encoding="utf-8"))
    # Pydantic camelCase alias places it at agents.defaults.user.name
    assert data["agents"]["defaults"]["user"]["name"] == "<your-name>"


def test_user_name_persists_when_overridden(tmp_path):
    from femtobot.utils.helpers import build_default_onboard_config

    cfg = build_default_onboard_config(tmp_path)
    cfg.agents.defaults.user.name = "Bill Kopp"
    # The override must survive — no re-template, no normalisation
    assert cfg.agents.defaults.user.name == "Bill Kopp"
