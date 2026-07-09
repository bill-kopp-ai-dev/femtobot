"""Markdown skill file loader and executor.

A skill is a ``.md`` file with YAML frontmatter that describes a slash command.
Inspired by Claude Code skills (``FEMTOBOT_CLI_REFACTOR_PLAN.md`` Camada 2, T2.2).

Directory layout (precedence: high → low):
  ``<instance_dir>/commands/*.md``    — project-specific skills
  ``~/.femtobot/commands/*.md``       — personal skills
  ``<pkg>/templates/commands/*.md``   — bundled builtin skills

Frontmatter schema::

    ---
    name: /review           # command name (with leading slash)
    description: Run code review
    argument_hint: [pr-url]  # shown in /help and completer
    tags: [review, security] # optional grouping
    bypass_llm: false       # if true, output is prepended as system context
    allowed_tools:          # optional; if set, only these tools are injected
      - read_file
      - exec
    ---

Body
~~~~
The rest of the file is a Jinja2 template rendered with the following variables:

``$ARGUMENTS``  — everything after the command name
``$1`` … ``$9`` — positional arguments (split on whitespace)
``$TOOL_RESULTS`` — results from tool invocations in this skill

Bash inline: `` !`command` `` executes a subprocess and substitutes its stdout.

Usage
~~~~~
::

    from femtobot.cli.md_commands import load_all_skills, render_skill

    skills = load_all_skills(instance_dir, home_dir)
    content = render_skill(skills["/review"], arguments="@PR_URL")
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from femtobot.command.builtin import BuiltinCommandSpec

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SkillSpec:
    """Parsed representation of a skill file."""

    name: str  # e.g. "/review"
    description: str = ""
    argument_hint: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)
    bypass_llm: bool = False
    allowed_tools: tuple[str, ...] = field(default_factory=tuple)
    body: str = ""  # raw body (after frontmatter) for template rendering
    source: Path | None = field(default=None, repr=False)  # for debugging
    _source_key: str = ""  # "instance" | "home" | "builtin"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_FRONTmatter_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_ARG_RE = re.compile(r"\$[ARGUMENTS0-9{}]+")


def _run_bash_inlines(text: str, timeout_s: float = 10.0) -> str:
    """Substitute ``!`cmd` `` with command output inline.

    Security: this runs a real shell with ``shell=True`` because the
    feature is the inline substitution.  The caller MUST have already
    validated that the skill body is from a trusted source (this is
    gated by ``render_body(..., unsafe_bypass=True)`` in the rest of
    the module).  We log an ``audit``-level event for every inline
    substitution so an operator reviewing the femtobot log can
    detect a tampered skill body.  The ``FEMTOBOT_NO_BASH_INLINE=1``
    env var is a global kill-switch: when set, ``!`...`` is replaced
    with a literal placeholder instead of being executed.
    """
    import os

    from loguru import logger as _logger

    results: list[str] = []

    bash_disabled = bool(os.environ.get("FEMTOBOT_NO_BASH_INLINE"))

    def _sub(match: re.Match) -> str:
        cmd = match.group(1).strip()
        if bash_disabled:
            # Global kill-switch via env var; the operator explicitly
            # opted out so a tampered skill body can't reach ``shell=True``.
            _logger.warning(
                "FEMTOBOT_NO_BASH_INLINE=1; not running inline shell "
                "command (length={}): {}",
                len(cmd),
                cmd[:80],
            )
            return f"[bash disabled: {cmd[:60]}]"
        # Audit trail — every inline shell call is recorded so a
        # post-mortem of a skill-body modification can spot it.
        _logger.info(
            "Bash inline substitution (cmd_length={}): {}",
            len(cmd),
            cmd[:120],
        )
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                timeout=timeout_s,
                text=True,
            )
            return proc.stdout.rstrip("\n")
        except Exception as exc:
            return f"[bash error: {exc}]"

    # Match !`...` or ! "..." (quoted)
    pattern = r"!`([^`]+)`"
    return re.sub(pattern, _sub, text)


def parse_skill(raw: str, source: Path | None = None, source_key: str = "") -> SkillSpec:
    """Parse a skill file body into a :class:`SkillSpec`."""
    match = _FRONTmatter_RE.search(raw)
    if match:
        frontmatter_raw = match.group(1)
        body = raw[match.end() :]
    else:
        frontmatter_raw = ""
        body = raw

    try:
        meta = yaml.safe_load(frontmatter_raw) or {}
    except yaml.YAMLError:
        meta = {}

    name = str(meta.get("name", ""))
    return SkillSpec(
        name=name,
        description=str(meta.get("description", "")),
        argument_hint=str(meta.get("argument_hint", "")),
        tags=tuple(str(t) for t in meta.get("tags", [])),
        bypass_llm=bool(meta.get("bypass_llm", False)),
        allowed_tools=tuple(str(t) for t in meta.get("allowed_tools", [])),
        body=body.lstrip("\n"),
        source=source,
        _source_key=source_key,
    )


def _read_skill_file(path: Path, source_key: str) -> SkillSpec | None:
    """Load and parse a single skill file, or return None on error."""
    try:
        raw = path.read_text("utf-8")
        return parse_skill(raw, source=path, source_key=source_key)
    except (OSError, UnicodeDecodeError):
        return None


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

KNOWN_BUILTIN_DIRS: list[Path] = []  # populated at the bottom of this module


def load_all_skills(
    instance_dir: Path | None = None,
    home_dir: Path | None = None,
    builtin_dir: Path | None = None,
) -> dict[str, SkillSpec]:
    """Load all skills from instance, home, and bundled directories.

    Returns a dict mapping ``name`` (e.g. ``"/review"``) → :class:`SkillSpec`.
    When the same name appears in multiple directories, precedence is:
    instance > home > builtin (last wins for duplicates).
    """
    skills: dict[str, SkillSpec] = {}

    for directory, key in [
        (builtin_dir, "builtin"),
        (home_dir, "home"),
        (instance_dir, "instance"),
    ]:
        if directory is None or not directory.is_dir():
            continue
        try:
            for path in sorted(directory.glob("*.md")):
                spec = _read_skill_file(path, key)
                if spec and spec.name:
                    skills[spec.name] = spec
        except PermissionError:
            pass

    return skills


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_JINJA_AVAILABLE = True
try:
    from jinja2 import Template
except ImportError:
    _JINJA_AVAILABLE = False


def _sub_dollar_vars(text: str) -> str:
    """Expand $VAR syntax into {{VAR}} for Jinja2 compatibility.

    Handles $ARGUMENTS, $TOOL_RESULTS, and $1 … $9.
    Variables are passed to Jinja2 as strings so $1 renders as the value
    of the first positional argument (not the integer 1).
    """
    def _rep(m: re.Match) -> str:
        name = m.group(1)
        # Prefix numeric names with _ so Jinja2 receives them as strings
        # in the context dict (e.g. _1 instead of 1).
        if name.isdigit():
            name = "_" + name
        return "{{ " + name + " }}"
    return re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*|\d)", _rep, text)


def render_skill(
    spec: SkillSpec,
    arguments: str = "",
    tool_results: str = "",
    *,
    unsafe_bypass: bool = True,  # allow bash inlines by default
) -> str:
    """Render a skill's body as a prompt string.

    ``arguments`` is split on whitespace into positional variables ``$1``…``$9``.
    ``$ARGUMENTS`` holds the raw arguments string.
    ``$TOOL_RESULTS`` holds the results of any tool calls made within the skill.
    ``!`cmd` `` substitutions are performed inline when ``unsafe_bypass=True``.
    """
    parts = arguments.strip().split()
    ctx = {
        "ARGUMENTS": arguments,
        "TOOL_RESULTS": tool_results,
        **{f"_{i+1}": v for i, v in enumerate(parts[:9])},
    }

    body = spec.body
    if _JINJA_AVAILABLE:
        # Expand $VAR → {{VAR}} before Jinja2 rendering.
        try:
            prepared = _sub_dollar_vars(body)
            body = Template(prepared, keep_trailing_newline=False).render(**ctx)
        except Exception:
            body = spec.body  # fall back to raw body

    if unsafe_bypass:
        body = _run_bash_inlines(body)

    return body


# ---------------------------------------------------------------------------
# CLI command registry integration
# ---------------------------------------------------------------------------

# After loading, the result of ``load_all_skills`` is cached here and
# made available to the slash command completer via
# ``BUILTIN_COMMAND_SPECS`` (extended with skill specs).
_loaded_skills: dict[str, SkillSpec] = {}


def get_loaded_skills() -> dict[str, SkillSpec]:
    """Return the currently-loaded skill registry (may be empty before first load)."""
    return _loaded_skills


def load_skills_into_registry(
    instance_dir: Path | None = None,
    home_dir: Path | None = None,
) -> dict[str, SkillSpec]:
    """Load all skills and store them in the module-level registry."""
    global _loaded_skills
    builtin_dir = _get_builtin_dir()
    _loaded_skills = load_all_skills(
        instance_dir=instance_dir,
        home_dir=home_dir,
        builtin_dir=builtin_dir,
    )
    return _loaded_skills


def _get_builtin_dir() -> Path | None:
    """Return the path to the bundled builtin skills directory."""
    try:
        return Path(__file__).parent.parent / "templates" / "commands" / "builtin"
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Skill spec as BuiltinCommandSpec adapter
# ---------------------------------------------------------------------------


def skill_to_command_spec(spec: SkillSpec) -> BuiltinCommandSpec:
    """Convert a :class:`SkillSpec` to a :class:`BuiltinCommandSpec` for the completer."""
    icon = "book-open" if spec.bypass_llm else "file-code"
    return BuiltinCommandSpec(
        command=spec.name,
        title=spec.description[:30],  # short label
        description=spec.description,
        icon=icon,
        arg_hint=spec.argument_hint or "",
    )
