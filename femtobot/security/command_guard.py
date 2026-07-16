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
) -> tuple[bool, str]:
    """Best-effort safety guard for potentially destructive commands."""
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
        allow_loopback=current_scope_allows_loopback(enabled=False),
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
