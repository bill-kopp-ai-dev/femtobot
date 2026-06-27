"""Tool hint formatting for concise, human-readable tool call display."""

from __future__ import annotations

import re

from femtobot.utils.path import abbreviate_path

# Registry: tool_name -> (key_args, template, is_path, is_command)
_TOOL_FORMATS: dict[str, tuple[list[str], str, bool, bool]] = {
    "read_file": (["path", "file_path"], "read {}", True, False),
    "write_file": (["path", "file_path"], "write {}", True, False),
    "edit": (["file_path", "path"], "edit {}", True, False),
    "find_files": (["query", "glob", "path"], "find {}", False, False),
    "grep": (["pattern"], 'grep "{}"', False, False),
    "exec": (["command"], "$ {}", False, True),
    "list_exec_sessions": ([], "exec sessions", False, False),
    "web_search": (["query"], 'search "{}"', False, False),
    "web_fetch": (["url"], "fetch {}", True, False),
    "list_dir": (["path"], "ls {}", True, False),
}

# Capability tags for MCP-wrapped tools.
# Keys are the *bare* MCP tool names (without the `mcp_<server>_` prefix).
# Tags appear in the tool hint as ``[tag1, tag2]`` so the model can see at
# a glance whether a tool is long-running or requires confirmation.
#
# Refs: FEMTOBOT_MCP_IMPROVEMENT_PLAN.md Fase 2.
_MCP_TOOL_METADATA: dict[str, tuple[str, ...]] = {
    "agy_run_task": ("long-running", "safe-mode:confirm"),
    "claude_run_task": ("long-running", "safe-mode:confirm"),
    "agy_health": ("read-only", "cheap"),
    "agy_self_test": ("read-only", "cheap"),
    "claude_health": ("read-only", "cheap"),
}


def get_mcp_tool_metadata(tool_name: str) -> tuple[str, ...]:
    """Return capability tags for an MCP-wrapped tool.

    Uses suffix matching to handle both wrapped (``mcp_<server>_<tool>``)
    and bare (``<tool>``) names. Falls back to an empty tuple when no
    known tool suffix matches — by design, absence of tags means
    "no special capability hints apply".

    Suffix matching is preferred over a single prefix-strip because the
    sanitization step (``-`` -> ``_`` + collapse runs) makes the server
    portion of the wrapped name ambiguous to parse.
    """
    if tool_name in _MCP_TOOL_METADATA:
        return _MCP_TOOL_METADATA[tool_name]
    for bare_name, tags in _MCP_TOOL_METADATA.items():
        if tool_name.endswith("_" + bare_name):
            return tags
    return ()


def _strip_mcp_tool_prefix(tool_name: str) -> str:
    """Best-effort strip of ``mcp_<server>_`` prefix from *tool_name*.

    Examples:
        ``mcp_agy_mcp_server_agy_run_task`` -> ``agy_run_task``
        ``mcp_claude_code_cli_mcp_claude_health`` -> ``claude_health``
        ``agy_run_task`` -> ``agy_run_task`` (no prefix to strip)

    Note: this helper is intentionally approximate — after sanitization,
    ``agy-mcp-server`` becomes ``agy_mcp_server`` which makes the
    server/tool boundary ambiguous. Prefer
    :func:`get_mcp_tool_metadata` for capability lookups.
    """
    if not tool_name.startswith("mcp_"):
        return tool_name
    body = tool_name[len("mcp_") :]
    if "__" in body:
        return body.split("__", 1)[1]
    return body.split("_", 1)[1] if "_" in body else body

# Matches file paths embedded in shell commands, including quoted paths with spaces.
_PATH_IN_CMD_RE = re.compile(
    r'"(?P<double>(?:[A-Za-z]:[/\\]|~/|/)[^"]+)"'
    r"|'(?P<single>(?:[A-Za-z]:[/\\]|~/|/)[^']+)'"
    r"|(?P<bare>(?:[A-Za-z]:[/\\]|~/|(?<=\s)/)[^\s;&|<>\"']+)"
)


def format_tool_hints(tool_calls: list, max_length: int = 40) -> str:
    """Format tool calls as concise hints with smart abbreviation."""
    if not tool_calls:
        return ""

    formatted = []
    for tc in tool_calls:
        fmt = _TOOL_FORMATS.get(tc.name)
        if fmt:
            formatted.append(_fmt_known(tc, fmt, max_length))
        elif tc.name.startswith("mcp_"):
            formatted.append(_fmt_mcp(tc, max_length))
        else:
            formatted.append(_fmt_fallback(tc, max_length))

    hints = []
    for hint in formatted:
        if hints and hints[-1][0] == hint:
            hints[-1] = (hint, hints[-1][1] + 1)
        else:
            hints.append((hint, 1))

    return ", ".join(f"{h} \u00d7 {c}" if c > 1 else h for h, c in hints)


def _get_args(tc) -> dict:
    """Extract args dict from tc.arguments, handling list/dict/None/empty."""
    if tc.arguments is None:
        return {}
    if isinstance(tc.arguments, list):
        return tc.arguments[0] if tc.arguments else {}
    if isinstance(tc.arguments, dict):
        return tc.arguments
    return {}


def _extract_arg(tc, key_args: list[str]) -> str | None:
    """Extract the first available value from preferred key names."""
    args = _get_args(tc)
    if not isinstance(args, dict):
        return None
    for key in key_args:
        val = args.get(key)
        if isinstance(val, str) and val:
            return val
    for val in args.values():
        if isinstance(val, str) and val:
            return val
    return None


def _fmt_known(tc, fmt: tuple, max_length: int = 40) -> str:
    """Format a registered tool using its template."""
    if not fmt[0] and "{}" not in fmt[1]:
        return fmt[1]
    val = _extract_arg(tc, fmt[0])
    if val is None:
        return tc.name
    if fmt[2]:  # is_path
        val = abbreviate_path(val, max_len=max_length)
    elif fmt[3]:  # is_command
        val = _abbreviate_command(val, max_len=max_length)
    return fmt[1].format(val)


def _abbreviate_command(cmd: str, max_len: int = 40) -> str:
    """Abbreviate paths in a command string, then truncate."""
    path_max = max(max_len // 2, 25)

    def _replace_path(match: re.Match[str]) -> str:
        if match.group("double") is not None:
            return f'"{abbreviate_path(match.group("double"), max_len=path_max)}"'
        if match.group("single") is not None:
            return f"'{abbreviate_path(match.group('single'), max_len=path_max)}'"
        return abbreviate_path(match.group("bare"), max_len=path_max)

    abbreviated = _PATH_IN_CMD_RE.sub(_replace_path, cmd)
    if len(abbreviated) <= max_len:
        return abbreviated
    return abbreviated[: max_len - 1] + "\u2026"


def _fmt_mcp(tc, max_length: int = 40) -> str:
    """Format MCP tool as ``server::tool`` with optional capability tags."""
    name = tc.name
    if "__" in name:
        parts = name.split("__", 1)
        server = parts[0].removeprefix("mcp_")
        tool = parts[1]
    else:
        rest = name.removeprefix("mcp_")
        parts = rest.split("_", 1)
        server = parts[0] if parts else rest
        tool = parts[1] if len(parts) > 1 else ""
    if not tool:
        return name
    args = _get_args(tc)
    val = next((v for v in args.values() if isinstance(v, str) and v), None)
    base = (
        f'{server}::{tool}("{abbreviate_path(val, max_length)}")'
        if val
        else f"{server}::{tool}"
    )
    tags = get_mcp_tool_metadata(name)
    if tags:
        return f"{base} [{', '.join(tags)}]"
    return base


def _fmt_fallback(tc, max_length: int = 40) -> str:
    """Original formatting logic for unregistered tools."""
    args = _get_args(tc)
    val = next(iter(args.values()), None) if isinstance(args, dict) else None
    if not isinstance(val, str):
        return tc.name
    return (
        f'{tc.name}("{abbreviate_path(val, max_length)}")'
        if len(val) > max_length
        else f'{tc.name}("{val}")'
    )
