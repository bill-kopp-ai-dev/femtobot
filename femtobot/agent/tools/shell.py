"""Shell execution tool."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import Field

from femtobot.agent.tools._constants import SHELL_MAX_OUTPUT_CHARS, SHELL_MAX_TIMEOUT_S
from femtobot.agent.tools.base import Tool, tool_parameters
from femtobot.agent.tools.context import current_request_session_key
from femtobot.agent.tools.path_utils import resolve_default_cwd
from femtobot.agent.tools.exec_session import (
    DEFAULT_EXEC_SESSION_MANAGER,
    DEFAULT_MAX_OUTPUT_CHARS,
    DEFAULT_YIELD_MS,
    MAX_OUTPUT_CHARS,
    MAX_YIELD_MS,
    clamp_session_int,
    format_session_poll,
)
from femtobot.agent.tools.sandbox import wrap_command
from femtobot.agent.tools.schema import (
    BooleanSchema,
    IntegerSchema,
    StringSchema,
    tool_parameters_schema,
)
from femtobot.config.schema import Base
from femtobot.security.command_guard import (
    DESTRUCTIVE_DENY_PATTERNS,
    check_command_safety,
)
from femtobot.security.workspace_access import current_tool_workspace
from femtobot.security.workspace_policy import WORKSPACE_BOUNDARY_NOTE, is_path_within

_IS_WINDOWS = sys.platform == "win32"


class ExecToolConfig(Base):
    """Shell exec tool configuration."""

    enable: bool = True
    timeout: int = Field(
        default=60, ge=0
    )  # Hard timeout (s); 0 = no limit. Not capped by the per-call max.
    path_append: str = ""
    sandbox: str = ""
    allowed_env_keys: list[str] = Field(default_factory=list)
    allow_patterns: list[str] = Field(default_factory=list)
    deny_patterns: list[str] = Field(default_factory=list)


@dataclass(slots=True)
class _PreparedCommand:
    command: str
    cwd: str
    env: dict[str, str]
    timeout: int | None
    shell_program: str | None
    login: bool


@tool_parameters(
    tool_parameters_schema(
        command=StringSchema("The shell command to execute"),
        cmd=StringSchema("Compatibility alias for command"),
        working_dir=StringSchema("Optional working directory for the command"),
        workdir=StringSchema("Compatibility alias for working_dir"),
        timeout=IntegerSchema(
            60,
            description=(
                "Timeout in seconds. Increase for long-running commands "
                "like compilation or installation (default 60, max 600)."
            ),
            minimum=1,
            maximum=600,
        ),
        shell=StringSchema(
            "Optional shell binary to launch. On Unix, supports sh, bash, or zsh.",
            nullable=True,
        ),
        login=BooleanSchema(
            description="Whether to run bash/zsh with login shell semantics (default true).",
            default=True,
            nullable=True,
        ),
        yield_time_ms=IntegerSchema(
            description=(
                "Optional milliseconds to wait before returning output. "
                "When set, a still-running command returns a session_id that "
                "can be polled or written to with write_stdin. Omit this field "
                "to keep one-shot exec behavior."
            ),
            minimum=0,
            maximum=MAX_YIELD_MS,
            nullable=True,
        ),
        max_output_chars=IntegerSchema(
            description=(
                "Maximum output characters to return when yield_time_ms is used "
                "(default 10000, max 50000)."
            ),
            minimum=1000,
            maximum=MAX_OUTPUT_CHARS,
            nullable=True,
        ),
        max_output_tokens=IntegerSchema(
            description=(
                "Compatibility alias for max_output_chars. The current runtime "
                "uses a character budget."
            ),
            minimum=1000,
            maximum=MAX_OUTPUT_CHARS,
            nullable=True,
        ),
    )
)
class ExecTool(Tool):
    """Tool to execute shell commands."""

    _scopes = {"core"}

    config_key = "exec"

    @classmethod
    def config_cls(cls):
        return ExecToolConfig

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return ctx.config.exec.enable

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        cfg = ctx.config.exec
        return cls(
            working_dir=ctx.workspace,
            timeout=cfg.timeout,
            restrict_to_workspace=ctx.config.restrict_to_workspace,
            sandbox=cfg.sandbox,
            path_append=cfg.path_append,
            allowed_env_keys=cfg.allowed_env_keys,
            allow_patterns=cfg.allow_patterns,
            deny_patterns=cfg.deny_patterns,
        )

    def __init__(
        self,
        timeout: int = 60,
        working_dir: str | None = None,
        deny_patterns: list[str] | None = None,
        allow_patterns: list[str] | None = None,
        restrict_to_workspace: bool = False,
        sandbox: str = "",
        path_append: str = "",
        allowed_env_keys: list[str] | None = None,
        session_manager: Any | None = None,
    ):
        self.timeout = timeout
        self.working_dir = working_dir
        self.sandbox = sandbox
        self.deny_patterns = (deny_patterns or []) + DESTRUCTIVE_DENY_PATTERNS
        self.allow_patterns = allow_patterns or []
        self.restrict_to_workspace = restrict_to_workspace
        self.path_append = path_append
        self.allowed_env_keys = allowed_env_keys or []
        self._session_manager = session_manager or DEFAULT_EXEC_SESSION_MANAGER

    @property
    def name(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
        return (
            "Execute a shell command and return its output. "
            "Use this for tests, builds, package commands, git commands, and "
            "other process execution. Prefer read_file/find_files/grep for "
            "inspection and apply_patch/write_file/edit_file for file changes "
            "instead of cat, shell find/grep, echo, or sed. "
            "Use -y or --yes flags to avoid interactive prompts. "
            "For long-running or interactive commands, pass yield_time_ms; "
            "if the command keeps running, exec returns a session_id that can "
            "be polled or written to with write_stdin. Output is truncated at "
            "10 000 chars; timeout defaults to 60s."
        )

    @property
    def exclusive(self) -> bool:
        return True

    async def execute(
        self,
        command: str | None = None,
        cmd: str | None = None,
        working_dir: str | None = None,
        workdir: str | None = None,
        timeout: int | None = None,
        shell: str | None = None,
        login: bool | None = None,
        yield_time_ms: int | None = None,
        max_output_chars: int | None = None,
        max_output_tokens: int | None = None,
        **kwargs: Any,
    ) -> str:
        command = command or cmd
        working_dir = working_dir or workdir
        if not command:
            return "Error: Missing command. Provide command or cmd."
        if max_output_chars is None:
            max_output_chars = max_output_tokens

        prepared = self._prepare_command(command, working_dir, timeout, shell, login)
        if isinstance(prepared, str):
            return prepared

        if yield_time_ms is not None:
            return await self._execute_session(prepared, yield_time_ms, max_output_chars)

        try:
            process = await self._spawn(
                prepared.command,
                prepared.cwd,
                prepared.env,
                prepared.shell_program,
                prepared.login,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=prepared.timeout,
                )
            except asyncio.TimeoutError:
                await self._kill_process(process)
                return f"Error: Command timed out after {prepared.timeout} seconds"
            except asyncio.CancelledError:
                await self._kill_process(process)
                raise

            output_parts = []

            if stdout:
                output_parts.append(stdout.decode("utf-8", errors="replace"))

            if stderr:
                stderr_text = stderr.decode("utf-8", errors="replace")
                if stderr_text.strip():
                    output_parts.append(f"STDERR:\n{stderr_text}")

            output_parts.append(f"\nExit code: {process.returncode}")

            result = "\n".join(output_parts) if output_parts else "(no output)"

            max_len = clamp_session_int(
                max_output_chars, SHELL_MAX_OUTPUT_CHARS, 1000, MAX_OUTPUT_CHARS
            )
            if len(result) > max_len:
                half = max_len // 2
                result = (
                    result[:half]
                    + f"\n\n... ({len(result) - max_len:,} chars truncated) ...\n\n"
                    + result[-half:]
                )

            return result

        except Exception as e:
            return f"Error executing command: {str(e)}"

    async def _execute_session(
        self,
        prepared: _PreparedCommand,
        yield_time_ms: int | None,
        max_output_chars: int | None,
    ) -> str:
        try:
            session_id, poll = await self._session_manager.start(
                command=prepared.command,
                cwd=prepared.cwd,
                env=prepared.env,
                timeout=prepared.timeout,
                shell_program=prepared.shell_program,
                login=prepared.login,
                yield_time_ms=clamp_session_int(yield_time_ms, DEFAULT_YIELD_MS, 0, MAX_YIELD_MS),
                owner_session_key=current_request_session_key(),
                max_output_chars=clamp_session_int(
                    max_output_chars,
                    DEFAULT_MAX_OUTPUT_CHARS,
                    1000,
                    MAX_OUTPUT_CHARS,
                ),
            )
            return format_session_poll(session_id, poll)
        except Exception as exc:
            return f"Error executing command: {exc}"

    def _resolve_timeout(self, timeout: int | None) -> int | None:
        """Resolve the effective hard timeout in seconds (None = no limit).

        A per-call timeout supplied by the model stays capped at _MAX_TIMEOUT so
        the LLM cannot request unbounded execution. The config-level default
        (self.timeout) may exceed that cap, and 0 disables the limit entirely
        for trusted long-running tasks (#3595).

        Bug fix (audit 2026-07-18): the previous ``if timeout:`` check
        treated ``timeout=0`` (explicit "disable limit") as falsy and
        silently fell through to the config default. The fix uses an
        explicit ``is not None`` check, so ``0`` is honored as "no limit".
        """
        if timeout is not None:
            return min(timeout, SHELL_MAX_TIMEOUT_S)
        if self.timeout and self.timeout > 0:
            return self.timeout
        return None

    def _prepare_command(
        self,
        command: str,
        working_dir: str | None = None,
        timeout: int | None = None,
        shell: str | None = None,
        login: bool | None = None,
    ) -> _PreparedCommand | str:
        access = current_tool_workspace(
            self.working_dir,
            restrict_to_workspace=self.restrict_to_workspace,
            sandbox_restricts_workspace=bool(self.sandbox),
        )
        workspace_root = (
            str(access.project_path) if access.project_path is not None else self.working_dir
        )
        # When the user did not pin a working_dir and there is no active
        # workspace scope, prefer the project root over the Femtobot workspace
        # so shell commands like ``ls femtobot/agent`` resolve against the
        # user's source tree (the directory that contains ``.femtobot``),
        # not the Femtobot internal workspace.  See
        # ``path_utils.resolve_default_cwd`` for the full policy.
        if not working_dir and not access.scope:
            project_root = resolve_default_cwd(
                workspace=Path(self.working_dir) if self.working_dir else None,
                restrict_to_workspace=access.restrict_to_workspace,
            )
            default_cwd = str(project_root)
        else:
            default_cwd = None
        cwd = working_dir or default_cwd or workspace_root or os.getcwd()

        # Prevent an LLM-supplied working_dir from escaping the configured
        # workspace when restrict_to_workspace is enabled (#2826). Without
        # this, a caller can pass working_dir="/etc" and then all absolute
        # paths under /etc would pass the _guard_command check that anchors
        # on cwd.
        if access.restrict_to_workspace and workspace_root:
            try:
                requested = Path(cwd).expanduser().resolve()
                resolved_root = Path(workspace_root).expanduser().resolve()
            except Exception:
                return "Error: working_dir could not be resolved" + WORKSPACE_BOUNDARY_NOTE
            if not is_path_within(requested, resolved_root):
                return (
                    "Error: working_dir is outside the configured workspace"
                    + WORKSPACE_BOUNDARY_NOTE
                )

        guard_error = self._guard_command(
            command,
            cwd,
            restrict_to_workspace=access.restrict_to_workspace,
        )
        if guard_error:
            return guard_error

        if self.sandbox:
            if _IS_WINDOWS:
                logger.warning(
                    "Sandbox '{}' is not supported on Windows; running unsandboxed",
                    self.sandbox,
                )
            else:
                workspace = workspace_root or cwd
                command = wrap_command(self.sandbox, command, workspace, cwd)
                cwd = str(Path(workspace).resolve())

        effective_timeout = self._resolve_timeout(timeout)
        env = self._build_env()

        if self.path_append:
            if _IS_WINDOWS:
                env["PATH"] = env.get("PATH", "") + os.pathsep + self.path_append
            else:
                env["FEMTOBOT_PATH_APPEND"] = self.path_append
                command = f'export PATH="$PATH{os.pathsep}$FEMTOBOT_PATH_APPEND"; {command}'

        shell_program, shell_error = self._resolve_shell(shell)
        if shell_error:
            return shell_error

        return _PreparedCommand(
            command=command,
            cwd=cwd,
            env=env,
            timeout=effective_timeout,
            shell_program=shell_program,
            login=True if login is None else login,
        )

    @staticmethod
    async def _spawn(
        command: str,
        cwd: str,
        env: dict[str, str],
        shell_program: str | None = None,
        login: bool = True,
        *,
        stdin: int = asyncio.subprocess.DEVNULL,
    ) -> asyncio.subprocess.Process:
        """Launch *command* in a platform-appropriate shell."""
        if _IS_WINDOWS:
            if "\n" in command:
                return await asyncio.create_subprocess_exec(
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    command,
                    stdin=stdin,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    env=env,
                )
            return await asyncio.create_subprocess_shell(
                command,
                stdin=stdin,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )
        shell_program = shell_program or shutil.which("bash") or "/bin/bash"
        args = [shell_program]
        shell_name = Path(shell_program).name.lower()
        if login and shell_name in {"bash", "bash.exe", "zsh", "zsh.exe"}:
            args.append("-l")
        args.extend(["-c", command])
        return await asyncio.create_subprocess_exec(
            *args,
            stdin=stdin,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )

    @staticmethod
    def _resolve_shell(shell: str | None) -> tuple[str | None, str | None]:
        if not shell:
            return None, None
        if _IS_WINDOWS:
            return None, "Error: shell parameter is not supported on Windows"
        if "\0" in shell or "\n" in shell or "\r" in shell:
            return None, "Error: shell contains invalid characters"
        allowed = {"sh", "bash", "zsh"}
        path = Path(shell).expanduser()
        if path.is_absolute():
            if path.name not in allowed:
                return None, f"Error: unsupported shell {shell!r}. Allowed: bash, sh, zsh"
            if not path.is_file() or not os.access(path, os.X_OK):
                return None, f"Error: shell is not executable: {shell}"
            return str(path), None
        if "/" in shell or "\\" in shell:
            return None, "Error: shell must be a shell name or absolute path"
        if shell not in allowed:
            return None, f"Error: unsupported shell {shell!r}. Allowed: bash, sh, zsh"
        resolved = shutil.which(shell)
        if not resolved:
            return None, f"Error: shell not found: {shell}"
        return resolved, None

    @staticmethod
    async def _kill_process(process: asyncio.subprocess.Process) -> None:
        """Kill a subprocess and reap it to prevent zombies."""
        process.kill()
        try:
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=5.0)
        finally:
            if not _IS_WINDOWS:
                try:
                    os.waitpid(process.pid, os.WNOHANG)
                except (ProcessLookupError, ChildProcessError) as e:
                    logger.debug("Process already reaped or not found: {}", e)

    def _build_env(self) -> dict[str, str]:
        """Build a minimal environment for subprocess execution.

        On Unix, only HOME/LANG/TERM are passed; ``bash -l`` sources the
        user's profile which sets PATH and other essentials.

        On Windows, ``cmd.exe`` has no login-profile mechanism, so a curated
        set of system variables (including PATH) is forwarded.  API keys and
        other secrets are still excluded.
        """
        if _IS_WINDOWS:
            sr = os.environ.get("SYSTEMROOT", r"C:\Windows")
            env = {
                "SYSTEMROOT": sr,
                "COMSPEC": os.environ.get("COMSPEC", f"{sr}\\system32\\cmd.exe"),
                "USERPROFILE": os.environ.get("USERPROFILE", ""),
                "HOMEDRIVE": os.environ.get("HOMEDRIVE", "C:"),
                "HOMEPATH": os.environ.get("HOMEPATH", "\\"),
                "TEMP": os.environ.get("TEMP", f"{sr}\\Temp"),
                "TMP": os.environ.get("TMP", f"{sr}\\Temp"),
                "PATHEXT": os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD"),
                "PATH": os.environ.get("PATH", f"{sr}\\system32;{sr}"),
                "PYTHONUNBUFFERED": "1",
                "APPDATA": os.environ.get("APPDATA", ""),
                "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", ""),
                "ProgramData": os.environ.get("ProgramData", ""),
                "ProgramFiles": os.environ.get("ProgramFiles", ""),
                "ProgramFiles(x86)": os.environ.get("ProgramFiles(x86)", ""),
                "ProgramW6432": os.environ.get("ProgramW6432", ""),
            }
            for key in self.allowed_env_keys:
                val = os.environ.get(key)
                if val is not None:
                    env[key] = val
            return env
        home = os.environ.get("HOME", "/tmp")
        env = {
            "HOME": home,
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "TERM": os.environ.get("TERM", "dumb"),
            "PYTHONUNBUFFERED": "1",
        }
        for key in self.allowed_env_keys:
            val = os.environ.get(key)
            if val is not None:
                env[key] = val
        return env

    def _guard_command(
        self,
        command: str,
        cwd: str,
        *,
        restrict_to_workspace: bool | None = None,
    ) -> str | None:
        """Best-effort safety guard for potentially destructive commands."""
        should_restrict = (
            self.restrict_to_workspace if restrict_to_workspace is None else restrict_to_workspace
        )
        ok, reason = check_command_safety(
            command,
            Path(cwd),
            allow_patterns=self.allow_patterns,
            deny_patterns=self.deny_patterns,
            restrict_to_workspace=should_restrict,
        )
        return None if ok else reason
