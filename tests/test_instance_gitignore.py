"""Regression tests for the instance-level .gitignore emitted by `onboard`.

Security context:
    `config.json` routinely contains provider API keys (`providers.*.apiKey`),
    webhook tokens, allowed-root lists, and other secrets. An earlier version
    of `create_instance_gitignore` emitted a `!config.json` exception that
    un-ignored `config.json`. If a user ran `git init` inside the instance
    directory, the un-ignored rule meant `config.json` (and every API key it
    contained) could be committed and pushed to a public repository.

    These tests guard the fix:
      * The shipped template MUST NOT un-ignore `config.json`.
      * The shipped template MUST ignore `.json` files broadly.
      * The shipped template MUST ignore `.env` files.
      * The function must remain idempotent (don't overwrite an existing file).

Refs: project_security review (2026-06-27).
"""

from __future__ import annotations

from pathlib import Path

from femtobot.utils.helpers import create_instance_gitignore

# ---------------------------------------------------------------------------
# Static-content checks on the shipped template
# ---------------------------------------------------------------------------


def _render_template(instance_dir: Path) -> str:
    """Render the gitignore that ``create_instance_gitignore`` would emit."""
    create_instance_gitignore(instance_dir)
    return (instance_dir / ".gitignore").read_text(encoding="utf-8")


def test_gitignore_ignores_config_json(tmp_path: Path) -> None:
    """The shipped gitignore MUST ignore ``config.json`` (the secret-bearing file)."""
    text = _render_template(tmp_path)
    # Either a broad `*.json` rule covers it, or there is an explicit
    # `config.json` rule. Both are acceptable — what matters is that there is
    # NO `!config.json` exception anywhere in the file.
    assert "*.json" in text or "config.json" in text, (
        "Expected a rule that ignores config.json (broad `*.json` or explicit)."
    )


def test_gitignore_does_not_unignore_config_json(tmp_path: Path) -> None:
    """No `!config.json` exception — that pattern is what caused the leak."""
    text = _render_template(tmp_path)
    # Acceptable: `!config.json` ONLY appears in comments (lines starting with `#`).
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("#"):
            continue
        assert line != "!config.json", (
            "SECURITY: instance .gitignore must not un-ignore config.json. "
            "Found `!config.json` as an active rule."
        )


def test_gitignore_ignores_env_files(tmp_path: Path) -> None:
    """``.env`` and `.env.*` must be ignored — they hold secrets too."""
    text = _render_template(tmp_path)
    assert ".env" in text, "Expected `.env` to be ignored."
    assert ".env.*" in text, "Expected `.env.*` to be ignored."


def test_gitignore_ignores_broad_json_yaml_toml(tmp_path: Path) -> None:
    """All common config file extensions are ignored by default."""
    text = _render_template(tmp_path)
    for pattern in ("*.json", "*.yaml", "*.yml", "*.toml"):
        assert pattern in text, f"Expected `{pattern}` to be ignored."


def test_gitignore_warns_about_secrets_in_header(tmp_path: Path) -> None:
    """The header comment makes the security intent explicit."""
    text = _render_template(tmp_path)
    lowered = text.lower()
    assert "secret" in lowered or "api key" in lowered or "credentials" in lowered, (
        "Header comment must explicitly warn against committing secrets."
    )


def test_gitignore_does_not_overwrite_existing(tmp_path: Path) -> None:
    """If the user already has a .gitignore, don't clobber it."""
    sentinel = "# user-controlled ignore file\n*.bak\n"
    existing = tmp_path / ".gitignore"
    existing.write_text(sentinel, encoding="utf-8")

    create_instance_gitignore(tmp_path)

    assert existing.read_text(encoding="utf-8") == sentinel


def test_gitignore_can_be_committed_safely_in_subdir_repo(tmp_path: Path) -> None:
    """Simulate ``git init`` + ``git add -A`` inside the instance dir.

    Even if the user initializes a fresh repo inside the instance directory,
    the dangerous file ``config.json`` MUST remain ignored so it cannot be
    accidentally committed.
    """
    import subprocess

    instance = tmp_path / "instance"
    instance.mkdir()
    create_instance_gitignore(instance)
    # Drop a config.json with a fake API key.
    (instance / "config.json").write_text(
        '{"providers": {"minimax": {"apiKey": "sk-leaked-123"}}}', encoding="utf-8"
    )
    # Drop a benign file that IS supposed to be ignored.
    (instance / "history").mkdir()

    subprocess.run(["git", "init", "-q"], cwd=instance, check=True)
    # `git check-ignore -v` exits 0 and prints the matching rule when a path
    # is ignored, and exits 1 when it is not. We assert config.json IS ignored.
    result = subprocess.run(
        ["git", "check-ignore", "-v", "config.json"],
        cwd=instance,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "SECURITY: config.json is NOT ignored by the shipped gitignore. "
        "If this test fails, an `!config.json` exception has been reintroduced. "
        f"stderr: {result.stderr!r}"
    )
