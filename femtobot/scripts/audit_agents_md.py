"""Static audit of AGENTS.md / SOUL.md for internal contradictions.

Added in PR 5.1 of the longlogs remediation plan. Walks the
``AgentDefaults`` template files plus the workspace bootstrap files,
splits them into ``## ``-level sections, and flags pairs of sections
that demand mutually exclusive behaviours (e.g. "be autonomous" vs
"ask the user when in doubt").

The script is pure: it never reads from the network, never writes to
the filesystem, and never imports Femtobot runtime modules (it can run
in a half-installed checkout). Used by ``femtobot doctor`` (PR 7.2) and
by the ``-m audit`` pytest marker.

Usage::

    python -m femtobot.scripts.audit_agents_md
    python -m femtobot.scripts.audit_agents_md /path/to/workspace
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

# Patterns that describe "be autonomous" / "act first" posture.
_AUTONOMY_PATTERNS = (
    re.compile(r"\b(autonomous|be autonomous|act (now|first|immediately))\b", re.IGNORECASE),
    re.compile(r"\b(do not ask|never ask|skip confirmation)\b", re.IGNORECASE),
    re.compile(r"\b(if a task needs a tool.*emit the tool call in the same turn)\b", re.IGNORECASE),
    re.compile(r"\bnever end a turn with\b", re.IGNORECASE),
)

# Patterns that describe "ask first" / "consult the user" posture.
_ASK_FIRST_PATTERNS = (
    re.compile(r"\bask the user\b", re.IGNORECASE),
    re.compile(r"\bconfirm (with|by asking)\b", re.IGNORECASE),
    re.compile(r"\bget (the user'?s? )?(approval|consent|confirmation)\b", re.IGNORECASE),
    re.compile(r"\bbefore (proceeding|taking action|executing), ask\b", re.IGNORECASE),
)

# Patterns that describe "be brief" / "minimalist" posture.
_MINIMAL_PATTERNS = (
    re.compile(r"\b(minimalist|minimal|concise|brief|terse)\b", re.IGNORECASE),
    re.compile(r"\b(do not write paragraphs|no preamble|no plans?)\b", re.IGNORECASE),
)

# Patterns that describe "elaborate" / "be thorough" posture.
_VERBOSE_PATTERNS = (
    re.compile(r"\b(detailed|verbose|thorough|exhaustive)\b", re.IGNORECASE),
    re.compile(r"\b(write paragraphs|provide context|explain in full)\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class AuditFinding:
    section: str
    file: str
    posture: str  # one of "autonomous", "ask_first", "minimal", "verbose"
    excerpt: str

    def to_dict(self) -> dict:
        return asdict(self)


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Return ``[(heading, body), ...]`` for every ``## ``-level section."""
    sections: list[tuple[str, str]] = []
    current_heading = "(preamble)"
    current_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current_lines or current_heading != "(preamble)":
                sections.append((current_heading, "\n".join(current_lines)))
            current_heading = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    sections.append((current_heading, "\n".join(current_lines)))
    return sections


def _classify(body: str) -> list[str]:
    """Return the postures detected in ``body``."""
    detected: list[str] = []
    for pat, label in (
        (_AUTONOMY_PATTERNS, "autonomous"),
        (_ASK_FIRST_PATTERNS, "ask_first"),
        (_MINIMAL_PATTERNS, "minimal"),
        (_VERBOSE_PATTERNS, "verbose"),
    ):
        if any(pat.search(body) for pat in pat):
            detected.append(label)
    return detected


def _excerpt(body: str, pattern: re.Pattern[str]) -> str:
    m = pattern.search(body)
    if not m:
        return ""
    start = max(0, m.start() - 30)
    end = min(len(body), m.end() + 60)
    return body[start:end].strip().replace("\n", " ")


def audit_text(name: str, text: str) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    for heading, body in _split_sections(text):
        for posture in _classify(body):
            findings.append(
                AuditFinding(
                    section=heading,
                    file=name,
                    posture=posture,
                    excerpt=_excerpt(body, _POSTURE_REGEX[posture]),
                )
            )
    return findings


_POSTURE_REGEX: dict[str, re.Pattern[str]] = {
    "autonomous": _AUTONOMY_PATTERNS[0],
    "ask_first": _ASK_FIRST_PATTERNS[0],
    "minimal": _MINIMAL_PATTERNS[0],
    "verbose": _VERBOSE_PATTERNS[0],
}


# Pairs of postures that contradict each other. Listed in the order the
# reporter prints them; this list also drives the contradiction check.
_CONTRADICTION_PAIRS: list[tuple[str, str, str]] = [
    ("autonomous", "ask_first", "Agent is told both to act autonomously and to ask first."),
    ("minimal", "verbose", "Agent is told both to be brief and to be verbose."),
]


def find_contradictions(findings: list[AuditFinding]) -> list[dict]:
    """Return a list of contradiction reports.

    Each report is a dict with keys ``kind``, ``explanations`` (one per
    file where the posture was detected) and ``sections`` (heading
    names). The schema is stable so ``femtobot doctor`` can render it.
    """
    seen_postures: dict[str, set[str]] = {}
    for f in findings:
        seen_postures.setdefault(f.posture, set()).add(f.file)
    reports: list[dict] = []
    for a, b, message in _CONTRADICTION_PAIRS:
        if a in seen_postures and b in seen_postures:
            reports.append(
                {
                    "kind": f"{a}_vs_{b}",
                    "message": message,
                    "postures": [a, b],
                    "files": sorted(seen_postures[a] | seen_postures[b]),
                }
            )
    return reports


def audit_workspace(workspace: Path) -> dict:
    """Run the audit over the workspace bootstrap files plus templates.

    Returns a JSON-serialisable dict; ``--json`` callers pass this
    directly to ``json.dumps``.

    The argument can be either a directory (then AGENTS.md / SOUL.md /
    USER.md are looked up inside it) or a single markdown file path.
    """
    if workspace.is_file():
        files = [workspace]
    else:
        files = [
            workspace / "AGENTS.md",
            workspace / "SOUL.md",
            workspace / "USER.md",
        ]
    findings: list[AuditFinding] = []
    files_seen: list[str] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        files_seen.append(path.name)
        findings.extend(audit_text(path.name, text))
    return {
        "workspace": str(workspace),
        "files_scanned": files_seen,
        "findings": [f.to_dict() for f in findings],
        "contradictions": find_contradictions(findings),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "workspace",
        nargs="?",
        default=".",
        help="Workspace directory containing AGENTS.md / SOUL.md / USER.md.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON report instead of the human-readable summary.",
    )
    args = parser.parse_args(argv)

    workspace = Path(args.workspace).expanduser().resolve()
    report = audit_workspace(workspace)
    if args.json:
        json.dump(report, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        if not report["findings"]:
            print(f"No posture directives found in {workspace}.")
        else:
            print(f"Scanned: {', '.join(report['files_scanned']) or '(none)'}")
            for f in report["findings"]:
                print(
                    f"  [{f['posture']:>11}] {f['file']} :: {f['section']}\n"
                    f"      excerpt: {f['excerpt']!r}"
                )
        if report["contradictions"]:
            print("\nCONTRADICTIONS:")
            for c in report["contradictions"]:
                print(f"  - {c['message']}")
                print(f"      files: {', '.join(c['files'])}")
    # Return a non-zero status whenever a contradiction is detected,
    # regardless of --json / human-readable mode, so CI / femtobot doctor
    # can rely on the exit code.
    return 1 if report["contradictions"] else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
