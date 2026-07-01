"""Tests for the md_commands module (Camada 2, T2.2)."""

from __future__ import annotations

from femtobot.cli.md_commands import (
    parse_skill,
    render_skill,
    skill_to_command_spec,
    SkillSpec,
)


def test_parse_frontmatter() -> None:
    # YAML interprets unquoted [...] as a list.
    raw = """---
name: /review
description: Review a PR
argument_hint: pr-url
tags:
  - code-review
  - security
bypass_llm: false
---
Body content here."""
    spec = parse_skill(raw)
    assert spec.name == "/review"
    assert spec.description == "Review a PR"
    assert spec.argument_hint == "pr-url"
    assert spec.tags == ("code-review", "security")
    assert spec.bypass_llm is False
    assert "Body content" in spec.body


def test_parse_no_frontmatter() -> None:
    raw = "Just a plain body without YAML."
    spec = parse_skill(raw)
    assert spec.name == ""
    assert spec.body == raw


def test_parse_body_with_frontmatter_separator() -> None:
    raw = "---\nname: /cmd\n---\nReal body."
    spec = parse_skill(raw)
    assert spec.name == "/cmd"
    assert spec.body == "Real body."


def test_render_substitutes_arguments() -> None:
    spec = SkillSpec(name="/test", description="", body="Args: $ARGUMENTS | 1: $1 | 2: $2")
    result = render_skill(spec, "foo bar baz")
    assert "foo bar baz" in result
    assert "foo" in result  # $1
    assert "bar" in result  # $2


def test_render_unknown_var_becomes_empty() -> None:
    """Unknown $VAR → Jinja2 → renders as empty string (no exception)."""
    spec = SkillSpec(name="/t", body="Hello $UNKNOWN_VAR and $1")
    result = render_skill(spec, "pos1 pos2")
    # Unknown $UNKNOWN_VAR → empty; $1 → "pos1"
    assert "pos1" in result
    assert "UNKNOWN_VAR" not in result
    assert "$UNKNOWN_VAR" not in result


def test_skill_to_command_spec() -> None:
    spec = SkillSpec(name="/review", description="Review PR", bypass_llm=False)
    cmd = skill_to_command_spec(spec)
    assert cmd.command == "/review"
    assert cmd.description == "Review PR"
    assert cmd.icon == "file-code"  # bypass_llm=False → file-code


def test_skill_to_command_spec_bypass_llm() -> None:
    spec = SkillSpec(name="/bypass", description="x", bypass_llm=True)
    cmd = skill_to_command_spec(spec)
    assert cmd.icon == "book-open"  # bypass_llm=True → book-open
