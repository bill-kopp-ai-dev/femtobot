import os
import re
from pathlib import Path

from femtobot.config.paths import get_media_dir
from femtobot.security.network import contains_internal_url
from femtobot.security.workspace_access import current_scope_allows_loopback
from femtobot.security.workspace_policy import WORKSPACE_BOUNDARY_NOTE, is_path_within

DESTRUCTIVE_DENY_PATTERNS = [
    r"\brm\s+-[rf]{1,2}\b",  # rm -r, rm -rf, rm -fr
    r"\bdel\s+/[fq]\b",  # del /f, del /q
    r"\brmdir\s+/s\b",  # rmdir /s
    r"(?:^|[;&|]\s*)format(?!=)\b",  # format (as standalone command only)
    r"\b(mkfs|diskpart)\b",  # disk operations
    r"\bdd\s+if=",  # dd
    r">\s*/dev/sd",  # write to disk
    r"\b(shutdown|reboot|poweroff)\b",  # system power
    r":\(\)\s*\{.*\};\s*:",  # fork bomb
    # Block writes to femtobot internal state files
    r">>?\s*\S*(?:history\.jsonl|\.dream_cursor)",  # > / >> redirect
    r"\btee\b[^|;&<>]*(?:history\.jsonl|\.dream_cursor)",  # tee / tee -a
    r"\b(?:cp|mv)\b(?:\s+[^\s|;&<>]+)+\s+\S*(?:history\.jsonl|\.dream_cursor)",  # cp/mv target
    r"\bdd\b[^|;&<>]*\bof=\S*(?:history\.jsonl|\.dream_cursor)",  # dd of=
    r"\bsed\s+-i[^|;&<>]*(?:history\.jsonl|\.dream_cursor)",  # sed -i
    # Self-replication guard (longlogs.txt 2026-07-15): block Femtobot
    # from bootstrapping sibling instances via ``exec`` — the agent
    # already has access to ``/home/bill/Codes/CLI-router-project`` and
    # nothing about a fresh ``.femtobot_ok`` benefits the user's task;
    # if a new instance is needed it should be created by the operator
    # directly.  This is a default-deny guard; users can override via
    # ``allow_patterns`` in ``ExecToolConfig`` if they really want this.
    r"\bfemtobot\b[^|;&<>]*\b(onboard|init|new)\b",  # femtobot onboard/init/new
    # R2-femtobot (refactor-parity-with-nanobot.md, Phase 2): even with
    # the ``--suffix`` flag removed, the agent can still materialise a
    # sibling ``.femtobot`` directory by (a) recursively copying the
    # existing one, or (b) writing into the instance ``config.json``.
    # Both paths are below the Femtobot-onboard regex (which only
    # matches the literal ``femtobot`` binary invocation), so we add
    # explicit patterns here as defence in depth.
    #
    # Word-boundary + closing-token anchored: ``\.femtobot`` must NOT be
    # followed by another dot or word char so we don't match
    # ``.femtobot/workspace/skills/...`` (legitimate reads inside the
    # instance) or ``.femtobot_ok_history`` (unrelated).  We allow
    # ``.femtobot`` as a target (no slash) or ``.femtobot/...`` (with
    # path separator) so ``cat .femtobot/config.json`` etc. keep
    # working — only the copy/move-into-instance case is blocked.
    # The leading-token class accepts whitespace OR a path separator so
    # ``cp -r /opt/proj/.femtobot /tmp/x`` (absolute source) is matched.
    r"\b(?:cp|mv|rsync|cp\s+-r|cp\s+-a)\b[^|;&<>]*?(?:^|[\s/])\.femtobot(?:/|\s|$)",
    # Same idea for the legacy ``.nanobot`` dir name (we don't ship it,
    # but a determined agent might try to clone from an unrelated
    # nanobot install — same defence).
    r"\b(?:cp|mv|rsync|cp\s+-r|cp\s+-a)\b[^|;&<>]*?(?:^|[\s/])\.nanobot(?:/|\s|$)",
    # Writing to the instance ``config.json``: covers shell redirects,
    # tee, dd, sed -i, and the cp/mv-target form.  The ``\.json`` form
    # matches ``config.json`` and avoids colliding with
    # ``config.jsonl`` (also a real filename in our codebase) thanks
    # to the word boundary at the end.  The ``(?:^|\s)`` prefix avoids
    # matching legitimate ``cat .femtobot/config.json`` reads.  The
    # middle char class allows whitespace, ``<`` (tee input
    # redirection), ``>`` (overwrite), and path separators — anything
    # that can legitimately appear between a command and its argument
    # without being a control-flow character we want to leave alone.
    r">>?\s*\S*\.femtobot/\S*config\.json\b",
    r"\btee\b[^|;&]*?\.femtobot/\S*config\.json\b",
    r"\bdd\b[^|;&<>]*?\bof=\S*\.femtobot/\S*config\.json\b",
    r"\bsed\s+-i[^|;&<>]*?\.femtobot/\S*config\.json\b",
    r"\b(?:cp|mv)\b(?:\s+[^\s|;&<>]+)+\s+\S*\.femtobot/\S*config\.json\b",
    # ``tar`` / ``zip`` packaging the .femtobot directory.  We can't
    # blanket-block ``tar`` because the operator uses it for legitimate
    # backups; instead we block when the *input* (the file or directory
    # being added to the archive) ends in ``.femtobot`` or lives under
    # one.  Same trailing-token semantics as the cp/mv patterns above.
    r"\btar\b[^|;&<>]*?(?:\.femtobot(?:/|\s|$)|\S+\.femtobot(?:/|\s|$))",
    # Same idea for ``zip`` / ``unzip`` / ``jar`` (a determined attacker
    # could use any archiver; ``tar`` is by far the most common).
    r"\b(?:zip|jar)\b[^|;&<>]*?\.femtobot(?:/|\s|$)",
    # ``python -c`` / ``python3 -c`` with ``.femtobot`` in the source.
    # The string in the -c argument is opaque to our regex, so we
    # match by the presence of the literal ``.femtobot`` token in the
    # argument.  This has a small false-positive risk for legitimate
    # Python one-liners that mention the directory by name (very
    # unusual), so we only block when the Python invocation *also*
    # targets a file/path operation keyword (``copy``, ``move``,
    # ``chdir``, ``mkdir``, ``write``, ``rmtree``, ``chmod``, etc.).
    # We use ``.`` (any char) for the body rather than a denial class
    # because ``shutil.copytree(\".femtobot\"...)`` contains both
    # ``;`` (statement separator) and ``\"`` (string literal) that
    # would break an aggressive deny class.  Two patterns cover the
    # two orderings (``copytree(\".femtobot\"...)`` and
    # ``chdir(...); rm(\".femtobot\")``).
    #
    # Note: we deliberately omit ``\\b`` before/after the action
    # keywords because compounds like ``copytree`` / ``move_to`` /
    # ``rmtree`` should still match.  We also drop the trailing-token
    # anchor here because the literal ``.femtobot`` is often followed
    # by a closing quote / comma inside the Python source string.
    r"\b(?:python|python3)\b.{0,300}?(?:copy|move|chdir|mkdir|write|rmtree|chmod).{0,300}?\.femtobot",
    r"\b(?:python|python3)\b.{0,300}?\.femtobot.{0,300}?(?:copy|move|chdir|mkdir|write|rmtree|chmod)",
]


BENIGN_DEVICE_PATHS = frozenset(
    {
        "/dev/null",
        "/dev/zero",
        "/dev/full",
        "/dev/random",
        "/dev/urandom",
        "/dev/stdin",
        "/dev/stdout",
        "/dev/stderr",
        "/dev/tty",
    }
)


def extract_absolute_paths(command: str) -> list[str]:
    # Windows: match drive-root paths like `C:\` as well as `C:\path\to\file`, and UNC paths like `\\server\share`
    # NOTE: `*` is required so `C:\` (nothing after the slash) is still extracted.
    win_paths = re.findall(
        r"(?<![A-Za-z])(?:[A-Za-z]:[^\s\"'|><;]*|\\\\[^\s\"'|><;]+(?:\\[^\s\"'|><;]+)*)", command
    )
    posix_paths = re.findall(r"(?:^|[\s|>'\"])(/[^\s\"'>;|<]+)", command)  # POSIX: /absolute only
    home_paths = re.findall(
        r"(?:^|[\s>'\"])(~[^\s\"'>;|<]*)", command
    )  # POSIX/Windows home shortcut: ~
    return win_paths + posix_paths + home_paths


def is_benign_device_path(path: str) -> bool:
    """Return True for kernel device files that should never be workspace-blocked."""
    if path in BENIGN_DEVICE_PATHS:
        return True
    return path.startswith("/dev/fd/")


def check_command_safety(
    command: str,
    workspace_root: Path | None,
    *,
    allow_patterns: list[str] | None = None,
    deny_patterns: list[str] | None = None,
    restrict_to_workspace: bool = False,
    loopback_enabled: bool = True,
) -> tuple[bool, str]:
    """Best-effort safety guard for potentially destructive commands.

    Args:
        loopback_enabled: Whether loopback URLs (127.0.0.1, localhost,
            ::1) are allowed in this turn. Defaults to True to preserve
            historical behavior; WebUI Full Access turns set this to
            True while restricted turns set False via
            ``current_scope_allows_loopback``.
    """
    cmd = command.strip()
    lower = cmd.lower()

    allow_patterns = allow_patterns or []
    deny_patterns = deny_patterns or DESTRUCTIVE_DENY_PATTERNS

    # allow_patterns take priority over deny_patterns so that users can
    # exempt specific commands (e.g. "rm -rf" inside a build directory)
    # from the hardcoded deny list via configuration.
    explicitly_allowed = bool(allow_patterns) and any(re.search(p, lower) for p in allow_patterns)

    if not explicitly_allowed:
        for pattern in deny_patterns:
            if re.search(pattern, lower):
                return False, "Error: Command blocked by deny pattern filter"

        if allow_patterns:
            return False, "Error: Command blocked by allowlist filter (not in allowlist)"

    if contains_internal_url(
        cmd,
        allow_loopback=current_scope_allows_loopback(enabled=loopback_enabled),
    ):
        # The runner turns this marker into a non-retryable security hint.
        return False, "Error: Command blocked by safety guard (internal/private URL detected)"

    if restrict_to_workspace:
        if "..\\" in cmd or "../" in cmd:
            return False, (
                "Error: Command blocked by safety guard (path traversal detected)"
                + WORKSPACE_BOUNDARY_NOTE
            )

        cwd_path = workspace_root.resolve() if workspace_root else Path.cwd()

        for raw in extract_absolute_paths(cmd):
            try:
                expanded = os.path.expandvars(raw.strip())
                # Match against the un-resolved path first.  On Linux,
                # /dev/stderr is a symlink to /proc/self/fd/2 and
                # ``Path.resolve()`` would mask the device-file intent.
                if is_benign_device_path(expanded):
                    continue
                p = Path(expanded).expanduser().resolve()
            except Exception:
                continue

            if is_benign_device_path(str(p)):
                continue

            media_path = get_media_dir().resolve()
            if p.is_absolute() and not (
                is_path_within(p, cwd_path) or is_path_within(p, media_path)
            ):
                return False, (
                    "Error: Command blocked by safety guard (path outside working dir)"
                    + WORKSPACE_BOUNDARY_NOTE
                )

    return True, "OK"
