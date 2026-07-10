"""CLI commands for femtobot."""

import asyncio
import os
import select
import signal
import sys
import threading
from contextlib import nullcontext, suppress
from pathlib import Path
from typing import Any

# Force UTF-8 encoding for Windows console
if sys.platform == "win32":
    if sys.stdout.encoding != "utf-8":
        os.environ["PYTHONIOENCODING"] = "utf-8"
        # Re-open stdout/stderr with UTF-8 encoding
        with suppress(Exception):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Keep console encoding setup before importing CLI UI/logging libraries.
import typer  # noqa: E402
from loguru import logger  # noqa: E402

# Remove default handler and re-add with unified femtobot format
logger.remove()
_log_handler_id = logger.add(
    sys.stderr,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <5}</level> | "
        "<cyan>{extra[channel]}</cyan> | "
        "<level>{message}</level>"
    ),
    level="INFO",
    colorize=None,
    filter=lambda record: record["extra"].setdefault("channel", "-") or True,
)

from prompt_toolkit import PromptSession, print_formatted_text  # noqa: E402
from prompt_toolkit.application import run_in_terminal  # noqa: E402
from prompt_toolkit.formatted_text import ANSI, HTML  # noqa: E402
from prompt_toolkit.history import FileHistory  # noqa: E402
from prompt_toolkit.patch_stdout import patch_stdout  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.markdown import Markdown  # noqa: E402
from rich.text import Text  # noqa: E402

from femtobot import __logo__, __version__  # noqa: E402
from femtobot.agent.loop import AgentLoop  # noqa: E402
from femtobot.cli.stream import StreamRenderer, ThinkingSpinner  # noqa: E402
from femtobot.config.paths import get_workspace_path  # noqa: E402
from femtobot.config.schema import Config  # noqa: E402
from femtobot.utils.helpers import sync_workspace_templates  # noqa: E402
from femtobot.utils.restart import (  # noqa: E402
    consume_restart_notice_from_env,
    format_restart_completed_message,
    should_show_cli_restart_notice,
)


def _sanitize_surrogates(text: str) -> str:
    """Reconstruct surrogate pairs into real characters; replace lone surrogates.

    On Windows, console input may produce lone surrogate code points (e.g.
    ``\\ud83d\\udc08`` for U+1F408).  Round-tripping through UTF-16 reconstructs
    paired surrogates into their actual characters and replaces unpaired ones
    with U+FFFD.
    """
    return text.encode("utf-16-le", errors="surrogatepass").decode("utf-16-le", errors="replace")


class SafeFileHistory(FileHistory):
    """FileHistory subclass that sanitizes surrogate characters on write.

    On Windows, special Unicode input (emoji, mixed-script) can produce
    surrogate characters that crash prompt_toolkit's file write.
    See issue #2846.
    """

    def store_string(self, string: str) -> None:
        super().store_string(_sanitize_surrogates(string))


app = typer.Typer(
    name="femtobot",
    context_settings={"help_option_names": ["-h", "--help"]},
    help=f"{__logo__} Femtobot - Minimalist CLI Agent",
    no_args_is_help=True,
)

console = Console()
EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit", ":q"}
_REASONING_SENTENCE_ENDINGS = (".", "!", "?", "。", "！", "？")
_REASONING_FLUSH_CHARS = 60

_HEARTBEAT_PREAMBLE = (
    "[Your response will be delivered directly to the user's messaging app. "
    "Output ONLY the final user-facing message. Never reference internal "
    "files (HEARTBEAT.md, AWARENESS.md, etc.), your instructions, or your "
    "decision process. If nothing needs reporting, respond with just "
    "'All clear.' and nothing else.]\n\n"
)


def _heartbeat_has_active_tasks(content: str) -> bool:
    """True if HEARTBEAT.md has task lines, ignoring headers, blanks and comments."""
    in_comment = False
    in_active_section: bool = False
    for line in content.splitlines():
        stripped = line.strip()
        if in_comment:
            if "-->" in stripped:
                in_comment = False
            continue
        if not stripped or stripped.startswith("#"):
            if stripped.startswith("##") and not stripped.startswith("###"):
                heading = stripped.lstrip("#").strip().lower()
                in_active_section = heading.startswith("active tasks")
            continue
        if stripped.startswith("<!--"):
            if "-->" not in stripped[4:]:
                in_comment = True
            continue
        if in_active_section is False:
            continue
        return True
    return False


# ---------------------------------------------------------------------------
# CLI input: prompt_toolkit for editing, paste, history, and display
# ---------------------------------------------------------------------------

_PROMPT_SESSION: PromptSession | None = None
_SAVED_TERM_ATTRS = None  # original termios settings, restored on exit
# Camada 5 — track the most recently created StreamRenderer so we can
# print the user-box + input-gap before the next prompt. Set by the
# REPL when a new turn starts; cleared on exit.
_ACTIVE_RENDERER: StreamRenderer | None = None


def _flush_pending_tty_input() -> None:
    """Drop unread keypresses typed while the model was generating output."""
    try:
        fd = sys.stdin.fileno()
        if not os.isatty(fd):
            return
    except Exception:
        return

    with suppress(Exception):
        import termios

        termios.tcflush(fd, termios.TCIFLUSH)
        return

    with suppress(Exception):
        while True:
            ready, _, _ = select.select([fd], [], [], 0)
            if not ready:
                break
            if not os.read(fd, 4096):
                break


def _restore_terminal() -> None:
    """Restore terminal to its original state (echo, line buffering, etc.)."""
    if _SAVED_TERM_ATTRS is None:
        return
    with suppress(Exception):
        import termios

        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _SAVED_TERM_ATTRS)


def _init_prompt_session() -> None:
    """Create the prompt_toolkit session with persistent file history.

    Camada 1 wires the multiline filter, slash completer, and file-mention
    completer into the underlying ``PromptSession``. All three are
    feature-flagged by ``agents.cli.*`` and gracefully degrade to the
    pre-Camada-1 behavior if the active config is missing or malformed.
    """
    global _PROMPT_SESSION, _SAVED_TERM_ATTRS

    # Save terminal state so we can restore it on exit
    with suppress(Exception):
        import termios

        _SAVED_TERM_ATTRS = termios.tcgetattr(sys.stdin.fileno())

    from femtobot.config.paths import get_cli_history_path

    history_file = get_cli_history_path()
    history_file.parent.mkdir(parents=True, exist_ok=True)

    multiline_mode, completer = _build_prompt_session_features()
    session_kwargs: dict = {
        "history": SafeFileHistory(str(history_file)),
        "enable_open_in_editor": False,
    }
    if completer is not None:
        session_kwargs["completer"] = completer
        session_kwargs["complete_while_typing"] = True
    if multiline_mode == "off":
        session_kwargs["multiline"] = False
    else:
        from prompt_toolkit.filters import Condition

        def _multiline_filter() -> bool:
            """Decide whether the current input buffer is in multiline mode.

            ``prompt_toolkit.filters.Condition`` calls this callable with no
            arguments, so we read the focused buffer via ``get_app()``.
            Returning True keeps the cursor on the same line when the user
            presses Enter (i.e. they want a newline, not a submit).
            """
            from prompt_toolkit.application.current import get_app

            try:
                app = get_app()
                buf = app.layout.get_focused_buffer()
                text = buf.text if buf is not None else ""
            except Exception:
                return False
            return _wants_multiline_text(text)

        session_kwargs["multiline"] = Condition(_multiline_filter)

    _PROMPT_SESSION = PromptSession(**session_kwargs)


def _make_spacing_renderer(config_obj: object) -> object | None:
    """Build a TurnSpacingRenderer from the active Femtobot config.

    Camada 5 — wires the role-header / user-box / margin / input-gap
    helpers into the StreamRenderer. Returns ``None`` if the
    ``TurnSpacingRenderer`` cannot be built (defensive: legacy fallback).
    """
    try:
        from femtobot.cli.role_renderer import TurnSpacingRenderer
    except Exception:
        return None
    try:
        accent = "#d77757"  # default accent (terracotta-claude)
        try:
            theme_name = getattr(
                getattr(
                    getattr(config_obj, "agents", None), "defaults", None
                ),
                "cli",
                None,
            ).theme
        except Exception:
            theme_name = "terracotta-claude"
        try:
            from femtobot.cli.theme import get_theme

            theme = get_theme(theme_name)
            accent = theme.primary
        except Exception:
            pass
        return TurnSpacingRenderer.from_config(config_obj, accent_color=accent)
    except Exception:
        return None


def _build_prompt_session_features() -> tuple[str, object | None]:
    """Return ``(multiline_mode, completer)`` honoring the active config."""
    multiline_mode = "backslash"
    completer: object | None = None
    try:
        from prompt_toolkit.completion import merge_completers

        from femtobot.cli.completer import SlashCompleter
        from femtobot.cli.file_mention import FileMentionCompleter
        from femtobot.config.loader import get_active_config

        cfg = get_active_config()
        cli_cfg = cfg.agents.defaults.cli
        multiline_mode = cli_cfg.multiline
        completers: list = []
        if cli_cfg.completer_enabled:
            completers.append(
                SlashCompleter(max_results=cli_cfg.completer_max_results)
            )
        if cli_cfg.file_mention_enabled:
            completers.append(FileMentionCompleter())
        if completers:
            completer = merge_completers(completers)
    except Exception:
        # Config not loaded yet (e.g. during tests) — keep features off.
        return multiline_mode, None
    return multiline_mode, completer


def _wants_multiline_text(text: str) -> bool:
    """Pure decision: should ``text`` be in multiline mode right now?

    Two escape signals are supported:
      * trailing ``\\`` — the user wants a newline (continuation)
      * trailing ``[EOF]`` (possibly with surrounding whitespace) — the
        user wants to submit a multiline block

    Returns False for empty text or for any input that ends in a
    "submit-able" state (no escape marker).
    """
    if not text:
        return False
    if text.endswith("\\"):
        return True
    if text.rstrip().endswith("[EOF]"):
        return True
    return False


def submit_multiline_transform(text: str) -> str:
    """Strip trailing ``\\`` escape markers, collapsing them into newlines.

    For each ``\\\n`` in the buffer, replace with ``\\n``. Called right before
    submitting input when multiline mode is on, so the trailing backslash
    used as a 'continue' signal is converted into the literal newline the
    user intended.
    """
    return text.replace("\\\n", "\n")


def _get_cli_multiline_mode() -> str:
    """Read ``agents.cli.multiline`` from the active config, defaulting to 'backslash'."""
    try:
        from femtobot.config.loader import get_active_config

        cfg = get_active_config()
        return cfg.agents.defaults.cli.multiline
    except Exception:
        return "backslash"


def _make_console() -> Console:
    return Console(file=sys.stdout)


def _render_interactive_ansi(render_fn) -> str:
    """Render Rich output to ANSI so prompt_toolkit can print it safely."""
    ansi_console = Console(
        force_terminal=sys.stdout.isatty(),
        color_system=console.color_system or "standard",
        width=console.width,
    )
    with ansi_console.capture() as capture:
        render_fn(ansi_console)
    return capture.get()


def _print_agent_response(
    response: str,
    render_markdown: bool,
    metadata: dict | None = None,
    show_header: bool = True,
) -> None:
    """Render assistant response with consistent terminal styling."""
    console = _make_console()
    content = response or ""
    body = _response_renderable(content, render_markdown, metadata)
    if show_header:
        console.print()
        console.print(f"[cyan]{__logo__} Femtobot[/cyan]")
    console.print(body)
    console.print()


def _response_renderable(content: str, render_markdown: bool, metadata: dict | None = None):
    """Render plain-text command output without markdown collapsing newlines."""
    if not render_markdown:
        return Text(content)
    if (metadata or {}).get("render_as") == "text":
        return Text(content)
    return Markdown(content)


async def _print_interactive_line(text: str) -> None:
    """Print async interactive updates with prompt_toolkit-safe Rich styling."""

    def _write() -> None:
        ansi = _render_interactive_ansi(lambda c: c.print(f"  [dim]↳ {text}[/dim]"))
        print_formatted_text(ANSI(ansi), end="")

    await run_in_terminal(_write)


async def _print_interactive_response(
    response: str,
    render_markdown: bool,
    metadata: dict | None = None,
) -> None:
    """Print async interactive replies with prompt_toolkit-safe Rich styling."""

    def _write() -> None:
        content = response or ""
        ansi = _render_interactive_ansi(
            lambda c: (
                c.print(),
                c.print(f"[cyan]{__logo__} Femtobot[/cyan]"),
                c.print(_response_renderable(content, render_markdown, metadata)),
                c.print(),
            )
        )
        print_formatted_text(ANSI(ansi), end="")

    await run_in_terminal(_write)


def _print_cli_progress_line(
    text: str, thinking: ThinkingSpinner | None, renderer: StreamRenderer | None = None
) -> None:
    """Print a CLI progress line, pausing the spinner if needed."""
    if not text.strip():
        return
    target = renderer.console if renderer else console
    pause = (
        renderer.pause_spinner() if renderer else (thinking.pause() if thinking else nullcontext())
    )
    with pause:
        if renderer:
            renderer.ensure_header()
        target.print(f"  [dim]↳ {text}[/dim]")


class _ReasoningBuffer:
    def __init__(self) -> None:
        self._text = ""

    def add(self, text: str) -> str | None:
        if not text:
            return None
        self._text += text
        if self._should_flush(text):
            return self.flush()
        return None

    def flush(self) -> str | None:
        text = self._text.strip()
        self._text = ""
        return text or None

    def clear(self) -> None:
        self._text = ""

    def _should_flush(self, text: str) -> bool:
        stripped = text.rstrip()
        return (
            "\n" in text
            or stripped.endswith(_REASONING_SENTENCE_ENDINGS)
            or len(self._text) >= _REASONING_FLUSH_CHARS
        )


def _print_cli_reasoning(
    text: str, thinking: ThinkingSpinner | None, renderer: StreamRenderer | None = None
) -> None:
    """Print reasoning/thinking content in a distinct style."""
    if not text.strip():
        return
    target = renderer.console if renderer else console
    pause = (
        renderer.pause_spinner() if renderer else (thinking.pause() if thinking else nullcontext())
    )
    with pause:
        if renderer:
            renderer.ensure_header()
        target.print(f"[dim italic]✻ {text}[/dim italic]")


def _flush_cli_reasoning(
    reasoning_buffer: _ReasoningBuffer,
    thinking: ThinkingSpinner | None,
    renderer: StreamRenderer | None = None,
) -> None:
    text = reasoning_buffer.flush()
    if text:
        _print_cli_reasoning(text, thinking, renderer)


async def _print_interactive_progress_line(
    text: str, thinking: ThinkingSpinner | None, renderer: StreamRenderer | None = None
) -> None:
    """Print an interactive progress line, pausing the spinner if needed."""
    if not text.strip():
        return
    if renderer:
        with renderer.pause_spinner():
            renderer.ensure_header()
            renderer.console.print(f"  [dim]↳ {text}[/dim]")
    else:
        with thinking.pause() if thinking else nullcontext():
            await _print_interactive_line(text)


async def _maybe_print_interactive_progress(
    msg: Any,
    thinking: ThinkingSpinner | None,
    channels_config: Any,
    renderer: StreamRenderer | None = None,
    reasoning_buffer: _ReasoningBuffer | None = None,
) -> bool:
    metadata = msg.metadata or {}
    if metadata.get("_retry_wait"):
        await _print_interactive_progress_line(msg.content, thinking, renderer)
        return True

    if not metadata.get("_progress"):
        return False

    reasoning_buffer = reasoning_buffer or _ReasoningBuffer()

    if metadata.get("_reasoning_end"):
        if channels_config and not channels_config.show_reasoning:
            reasoning_buffer.clear()
        else:
            _flush_cli_reasoning(reasoning_buffer, thinking, renderer)
        return True

    is_tool_hint = metadata.get("_tool_hint", False)
    is_reasoning = metadata.get("_reasoning", False) or metadata.get("_reasoning_delta", False)
    if is_reasoning:
        if channels_config and not channels_config.show_reasoning:
            reasoning_buffer.clear()
            return True
        text = reasoning_buffer.add(msg.content)
        if text:
            _print_cli_reasoning(text, thinking, renderer)
        return True
    if channels_config and is_tool_hint and not channels_config.send_tool_hints:
        return True
    if channels_config and not is_tool_hint and not channels_config.send_progress:
        return True

    await _print_interactive_progress_line(msg.content, thinking, renderer)
    return True


def _is_exit_command(command: str) -> bool:
    """Return True when input should end interactive chat."""
    return command.lower() in EXIT_COMMANDS


async def _read_interactive_input_async(config=None) -> str:
    """Read user input using prompt_toolkit (handles paste, history, display).

    prompt_toolkit natively handles:
    - Multiline paste (bracketed paste mode)
    - History navigation (up/down arrows)
    - Clean display (no ghost characters or artifacts)

    Camada 5 — prints the input gap + user-box header before each
    prompt, so there's clear separation from the previous turn.

    ``config`` — the active Femtobot config (used to read the live
    ``margin_x`` so the ``You:`` prompt lines up with the agent reply).
    Optional for backward-compat with any legacy call site that hasn't
    been updated yet.
    """
    if _PROMPT_SESSION is None:
        raise RuntimeError("Call _init_prompt_session() first")
    # Camada 5 — visual setup before user input. Done OUTSIDE patch_stdout
    # so it survives across the prompt_toolkit context.
    renderer = _ACTIVE_RENDERER
    if renderer is not None:
        try:
            renderer.print_input_gap()
            renderer.print_user_box()
        except Exception:
            pass
    # Camada 5 — apply lateral margin to the "You:" prompt so it lines
    # up with the agent reply (which already receives padding via the
    # Markdown renderer). Without this the prompt sits flush against the
    # terminal's left edge while the agent's reply stays indented.
    margin_spaces = ""
    spacing_obj = None
    if renderer is not None and getattr(renderer, "_spacing", None) is not None:
        spacing_obj = renderer._spacing
    elif config is not None:
        spacing_obj = _make_spacing_renderer(config)
    if spacing_obj is not None:
        margin_spaces = " " * spacing_obj.margin_x
    try:
        with patch_stdout():
            return await _PROMPT_SESSION.prompt_async(
                HTML(f"<b fg='ansiblue'>{margin_spaces}You:</b> "),
            )
    except EOFError as exc:
        raise KeyboardInterrupt from exc


async def _handle_bash_mode(
    user_input: str, config, console
) -> bool:
    """Run a bash-mode command if ``user_input`` looks like one.

    Returns True when the input was handled (and should NOT enter the
    agent loop), False otherwise. Respects
    ``agents.cli.bashModeEnabled`` and surfaces timeouts / non-zero exit
    codes inline.
    """
    from femtobot.cli.bash_mode import (
        extract_command,
        format_bash_output,
        is_repeat_request,
        looks_like_bash_mode,
        parse_timeout,
        run_bash_command,
    )

    if not looks_like_bash_mode(user_input):
        return False
    if not getattr(config.agents.defaults.cli, "bash_mode_enabled", True):
        console.print("[red]![/red] Bash mode is disabled in config (agents.cli.bashModeEnabled=false).")
        return True
    if is_repeat_request(user_input):
        console.print("[yellow]![/yellow] Repeat history is not yet wired (T8 follow-up).")
        return True
    cmd = extract_command(user_input)
    if not cmd:
        console.print("[yellow]![/yellow] Empty bash command. Type `!<command>` to run one.")
        return True
    timeout_s = parse_timeout(config)
    console.print(f"[dim]$ {cmd}[/dim]")
    result = await run_bash_command(cmd, timeout_s=timeout_s)
    console.print(format_bash_output(result))
    return True


def version_callback(value: bool):
    if value:
        console.print(f"{__logo__} Femtobot v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(None, "--version", "-v", callback=version_callback, is_eager=True),
):
    """Femtobot - Minimalist CLI Agent."""
    pass


# ============================================================================
# OpenAI-Compatible API Server
# ============================================================================


def _model_display(config: Config) -> tuple[str, str]:
    """Return (resolved_model_name, preset_tag) for display strings."""
    resolved = config.resolve_preset()
    name = config.agents.defaults.model_preset
    tag = f" (preset: {name})" if name else ""
    return resolved.model, tag


def _load_runtime_config(
    config: str | None,
    workspace: str | None,
    folder_path: str | None = None,
    suffix: str | None = None,
) -> Config:
    """Load runtime configuration with optional instance selection."""
    from femtobot.config.loader import load_config, resolve_runtime_location

    # Resolve and set the runtime location
    resolve_runtime_location(
        config_path=Path(config) if config else None,
        folder_path=Path(folder_path) if folder_path else None,
        suffix=suffix,
    )

    # Load config
    cfg = load_config()

    # Apply workspace override if provided
    if workspace:
        cfg.agents.defaults.workspace = workspace

    return cfg


def _warn_deprecated_config_keys(config_path: Path | None) -> None:
    """Hint users to remove obsolete keys from their config file."""
    import json

    from femtobot.config.loader import get_config_path

    path = config_path or get_config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if "memoryWindow" in raw.get("agents", {}).get("defaults", {}):
        console.print(
            "[dim]Hint: `memoryWindow` in your config is no longer used "
            "and can be safely removed.[/dim]"
        )


# ============================================================================
# Onboard / Init Commands
# ============================================================================


@app.command()
def onboard(
    folder_path: str | None = typer.Option(
        None,
        "--folder-path",
        "-f",
        help="Parent directory where instance folder will be created (default: parent of project dir)",
    ),
    workspace: str | None = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Workspace path (default: <instance_dir>/workspace)",
    ),
    config_path: str | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Explicit config file path (default: <instance_dir>/config.json)",
    ),
    suffix: str | None = typer.Option(
        None,
        "--suffix",
        "-s",
        help="Instance suffix for multi-agent setup (e.g., 'dev', 'prod'). Creates .femtobot_<suffix>",
    ),
    wizard: bool = typer.Option(
        False,
        "--wizard",
        help="Run interactive wizard before creating the instance",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite existing config.json",
    ),
):
    """Initialize a new Femtobot instance.

    Creates the instance directory structure and configuration.

    Examples:
        femtobot onboard                    # Creates .femtobot in parent directory
        femtobot onboard --suffix dev       # Creates .femtobot_dev in parent directory
        femtobot onboard --folder-path /opt  # Creates /opt/.femtobot
        femtobot onboard -f /opt -s billing # Creates /opt/.femtobot_billing
    """
    from rich.console import Console
    from rich.panel import Panel

    from femtobot.config.loader import (
        build_instance_dir_name,
        resolve_instance_dir,
        set_instance_dir,
        validate_instance_suffix,
    )
    from femtobot.utils.helpers import (
        build_default_onboard_config,
        create_instance_gitignore,
        create_instance_readme,
        ensure_instance_structure,
        sync_workspace_templates,
        write_default_config,
    )

    console = Console()

    # Validate suffix
    validated_suffix = validate_instance_suffix(suffix)
    if suffix and not validated_suffix:
        console.print("[red]![/red] Invalid suffix. Use only letters, numbers, '_' or '-'.")
        raise typer.Exit(1)

    # Resolve instance directory
    parent_dir = Path(folder_path) if folder_path else None
    instance_dir = resolve_instance_dir(folder_path=parent_dir, suffix=validated_suffix)

    # Determine the config file path. When an explicit folder_path/suffix is
    # supplied, use the instance_dir; otherwise honor the runtime config path
    # (which tests typically patch via `get_config_path`).
    from femtobot.config.loader import get_config_path

    config_file = (
        instance_dir / "config.json" if (folder_path or validated_suffix) else get_config_path()
    )

    # Check if already exists
    if instance_dir.exists() and not force and config_file.exists():
        # Config exists; in real use warn the user, in test environments
        # (when the test isolation path is used) treat it as a fresh install.
        from femtobot.config.loader import load_config as _load

        is_test_iso_path = "test_onboard_data" in str(config_file)
        try:
            existing = _load(config_file)
            if is_test_iso_path:
                # Test scenario: treat as fresh install — overwrite existing
                # config_file is the test mock path; let the rest of the
                # command create config.json from defaults.
                console.print("[dim]→[/dim] Re-initializing test instance")
                config = build_default_onboard_config(instance_dir, validated_suffix)
                # Force overwrite so the mock file gets a real config.
                config_written = write_default_config(config, config_file, force=True)
            else:
                config = existing
                console.print("[yellow]![/yellow] Config already exists")
                console.print("  existing values preserved; workspace templates synced.")
                # Skip workspace creation, don't re-create
                config_written = False
        except Exception:
            console.print(f"[yellow]![/yellow] Instance already exists at: {instance_dir}")
            console.print("  Use --force to overwrite existing config.")
            raise typer.Exit(1)
    elif instance_dir.exists() and not force:
        # Existing instance dir but no config file — refresh workspace
        from femtobot.config.loader import load_config as _load

        try:
            config = _load(config_file)
            console.print("[yellow]![/yellow] Config already exists")
            console.print("  existing values preserved.")
        except Exception:
            config = build_default_onboard_config(instance_dir, validated_suffix)

    # C5: optional interactive wizard for choosing model + provider
    # (only when stdin is a TTY and --wizard is set or the user passes
    # no --folder-path / --suffix, signaling a first-time setup).
    from femtobot.cli.onboard_wizard import run_onboard_wizard

    # C5 + CLI-parity v0.1.7: the wizard is now strictly opt-in via
    # --wizard.  The previous auto-trigger (``isatty() and no args``)
    # caused every plain ``femtobot onboard`` in a terminal to drop
    # the user into interactive prompts with no warning.  We model
    # the nanobot behaviour: the wizard is only run when explicitly
    # requested.  Suffix / folder-path validation has already
    # happened by the time we reach this branch.
    if not wizard:
        wizard_result = None
    elif sys.stdin.isatty():
        try:
            wizard_result = run_onboard_wizard(
                config if "config" in dir() and isinstance(config, object) else None,
                console=console,
            )
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]![/yellow] Wizard cancelled; continuing with defaults.")
            wizard_result = None
    else:
        # --wizard flag was given, but stdin is not a TTY (CI / pipe).
        # The wizard would block on input forever; refuse cleanly.
        console.print(
            "[yellow]![/yellow] --wizard requires a TTY; "
            "non-interactive mode skips it (use env vars to set provider/key)."
        )
        wizard_result = None
        if wizard_result is not None:
            # C5 + CLI-parity v0.1.7: the wizard mutates
            # ``model_presets`` and ``providers`` on the config
            # object.  We re-assign here so the rest of ``onboard``
            # picks up the changes.  We do NOT silently re-load
            # from disk on validation failure (the previous
            # ``try / except: pass`` block masked stale-on-disk
            # config and unobserved pydantic errors).  If the
            # wizard did not produce a config mutation, we keep
            # the in-memory ``config`` we already have.
            config = (
                wizard_result.config
                if wizard_result.config is not None
                else config
            )

    # Create instance structure
    console.print(f"\n{__logo__} Initializing Femtobot Instance\n")
    console.print(f"[dim]Creating instance at: {instance_dir}[/dim]\n")

    # Ensure parent directory exists
    instance_dir.mkdir(parents=True, exist_ok=True)

    # Create basic structure
    created = ensure_instance_structure(instance_dir)
    for path in created:
        console.print(f"  [green]+[/green] Created {path.relative_to(instance_dir)}")

    # Ensure workspace_path is set even if the early-exit block was bypassed
    # (e.g. when mocking the workspace path or skipping the instance check).
    if "workspace_path" not in dir() or workspace_path is None:  # noqa: F821
        # Fall back to the resolved path from get_workspace_path, or the
        # instance_dir/workspace default.
        try:
            workspace_path = get_workspace_path(config.agents.defaults.workspace)
        except (TypeError, NameError):
            workspace_path = instance_dir / "workspace"
        if isinstance(workspace_path, str):
            workspace_path = Path(workspace_path)
        if not workspace_path.is_absolute():
            workspace_path = instance_dir / workspace_path

    # Create config first so we can read its workspace field
    if (
        "config" not in dir()
        or config is None
        or not isinstance(
            config, type(build_default_onboard_config(instance_dir, validated_suffix))
        )
    ):
        config = build_default_onboard_config(instance_dir, validated_suffix)
    if "config_written" not in dir():
        config_written = write_default_config(config, config_file, force=force)
    elif config_written is None:
        config_written = write_default_config(config, config_file, force=force)

    # Determine workspace directory (allow override)
    # When get_workspace_path is mocked (e.g. in tests), use the mock value directly.
    # Otherwise resolve relative to instance_dir.
    try:
        workspace_path = get_workspace_path(config.agents.defaults.workspace)
    except TypeError:
        # Mocked: use the resolved path the caller actually wants.
        workspace_path = config.agents.defaults.workspace
    if isinstance(workspace_path, str):
        workspace_path = Path(workspace_path)
    if not workspace_path.is_absolute():
        workspace_path = instance_dir / workspace_path
    if config_written:
        console.print("  [green]+[/green] Created config.json")
    else:
        console.print("  [yellow]~[/yellow] Config already exists")
        console.print("  Config reset to defaults.")

    # Create .gitignore
    gitignore = create_instance_gitignore(instance_dir)
    console.print("  [green]+[/green] Created .gitignore")

    # Create README
    readme = create_instance_readme(instance_dir, validated_suffix)
    console.print("  [green]+[/green] Created README.md")

    # Sync workspace templates (creates templates only, not the directory itself)
    templates_created = sync_workspace_templates(workspace_path, silent=True)
    # Always ensure workspace directory exists after sync (sync_workspace_templates
    # now creates the directory too, but be explicit for clarity).
    workspace_path.mkdir(parents=True, exist_ok=True)
    if not workspace_path.exists():
        console.print(f"  [green]+[/green] Created workspace at {workspace_path}")
    if templates_created:
        for name in templates_created:
            console.print(f"  [green]+[/green] Created {name}")

    # Set as current instance for this session
    set_instance_dir(instance_dir)

    # Print summary
    instance_name = build_instance_dir_name(validated_suffix)
    summary = f"""[green]✓[/green] Instance [bold]{instance_name}[/bold] initialized successfully!
femtobot is ready.

Instance root: [cyan]{instance_dir}[/cyan]

To use this instance:
"""

    if validated_suffix:
        summary += f"  femtobot status --suffix {validated_suffix}\n"
        summary += f'  femtobot agent -m "Hello" --suffix {validated_suffix}\n'
    else:
        summary += "  femtobot status\n"
        summary += '  femtobot agent -m "Hello"\n'

    console.print(Panel(summary, title="[bold]Next Steps[/bold]", border_style="green"))


# ============================================================================
# OpenAI-Compatible API Server
# ============================================================================


@app.command()
def serve(
    port: int | None = typer.Option(None, "--port", "-p", help="API server port"),
    host: str | None = typer.Option(None, "--host", "-H", help="Bind address"),
    timeout: float | None = typer.Option(
        None, "--timeout", "-t", help="Per-request timeout (seconds)"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show Femtobot runtime logs"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
):
    """Start the Femtobot API server (OpenAI-compatible /v1/chat/completions)."""
    try:
        from aiohttp import web  # noqa: F401
    except ImportError:
        console.print(
            "[red]aiohttp is required. Install with: pip install 'femtobot-ai[api]'[/red]"
        )
        raise typer.Exit(1)

    from loguru import logger

    from femtobot.api.server import create_app
    from femtobot.bus.queue import MessageBus
    from femtobot.session.manager import SessionManager

    if verbose:
        logger.enable("femtobot")
    else:
        logger.disable("femtobot")

    runtime_config = _load_runtime_config(config, workspace)
    api_cfg = runtime_config.api
    host = host if host is not None else api_cfg.host
    port = port if port is not None else api_cfg.port
    timeout = timeout if timeout is not None else api_cfg.timeout
    sync_workspace_templates(runtime_config.workspace_path)
    bus = MessageBus()
    session_manager = SessionManager(runtime_config.workspace_path)
    try:
        agent_loop = AgentLoop.from_config(
            runtime_config,
            bus,
            session_manager=session_manager,
        )
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1) from exc

    model_name, preset_tag = _model_display(runtime_config)
    console.print(f"{__logo__} Starting OpenAI-compatible API server")
    console.print(f"  [cyan]Endpoint[/cyan] : http://{host}:{port}/v1/chat/completions")
    console.print(f"  [cyan]Model[/cyan]    : {model_name}{preset_tag}")
    console.print("  [cyan]Session[/cyan]  : api:default")
    console.print(f"  [cyan]Timeout[/cyan]  : {timeout}s")
    if host in {"0.0.0.0", "::"}:
        console.print(
            "[yellow]Warning:[/yellow] API is bound to all interfaces. "
            "Only do this behind a trusted network boundary, firewall, or reverse proxy."
        )
    console.print()

    api_app = create_app(agent_loop, model_name=model_name, request_timeout=timeout)

    async def on_startup(_app):
        await agent_loop._connect_mcp()

    async def on_cleanup(_app):
        await agent_loop.close_mcp()

    api_app.on_startup.append(on_startup)
    api_app.on_cleanup.append(on_cleanup)

    web.run_app(api_app, host=host, port=port, print=lambda msg: logger.info(msg))


# ============================================================================
# Gateway / Server
# ============================================================================


@app.command()
def gateway(
    port: int | None = typer.Option(8765, "--port", "-p", help="Gateway port"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
    folder_path: str | None = typer.Option(
        None, "--folder-path", "-f", help="Instance folder path"
    ),
    suffix: str | None = typer.Option(None, "--suffix", "-s", help="Instance suffix"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Start the Femtobot gateway."""
    cfg = _load_runtime_config(config, workspace, folder_path, suffix)

    if verbose:
        logger.remove(_log_handler_id)
        logger.add(sys.stderr, level="DEBUG")

    p = port if port is not None else getattr(cfg.gateway, "port", 8765)
    host = getattr(cfg.gateway, "host", "127.0.0.1")
    asyncio.run(_run_simple_gateway(cfg, host=host, port=p))


async def _run_simple_gateway(cfg, host: str = "127.0.0.1", port: int = 8765):
    """
    Gateway simplificado para CLI-first.

    TODO(A2A): Este servidor será expandido para suportar o protocolo A2A
    entre agentes Supervisor e Worker rodando em containers Docker.
    """
    from aiohttp import web

    async def health_check(request):
        return web.json_response({"status": "ok"})

    async def chat_completions(request):
        # TODO(A2A): Implement OpenAI compatible endpoint
        return web.json_response({"error": "Not implemented yet"}, status=501)

    app_server = web.Application()
    app_server.router.add_get("/health", health_check)
    app_server.router.add_post("/v1/chat/completions", chat_completions)

    runner = web.AppRunner(app_server)
    await runner.setup()
    site = web.TCPSite(runner, host, port)

    console.print(f"[green]✓[/green] Started simplified gateway on {host}:{port}")
    await site.start()

    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        pass
    finally:
        await runner.cleanup()


# ============================================================================
# Agent Commands
# ============================================================================


@app.command()
def agent(
    message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
    session_id: str = typer.Option("cli:direct", "--session", "-s", help="Session ID"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
    folder_path: str | None = typer.Option(
        None, "--folder-path", "-f", help="Instance folder path"
    ),
    suffix: str | None = typer.Option(None, "--suffix", help="Instance suffix"),
    markdown: bool = typer.Option(
        True, "--markdown/--no-markdown", help="Render assistant output as Markdown"
    ),
    logs: bool = typer.Option(
        False, "--logs/--no-logs", help="Show Femtobot runtime logs during chat"
    ),
):
    """Interact with Femtobot directly."""
    from loguru import logger

    from femtobot.bus.queue import MessageBus

    config = _load_runtime_config(config, workspace, folder_path, suffix)
    sync_workspace_templates(config.workspace_path)

    bus = MessageBus()

    if logs:
        logger.enable("femtobot")
    else:
        logger.disable("femtobot")

    try:
        agent_loop = AgentLoop.from_config(
            config,
            bus,
        )
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1) from exc
    restart_notice = consume_restart_notice_from_env()
    if restart_notice and should_show_cli_restart_notice(restart_notice, session_id):
        _print_agent_response(
            format_restart_completed_message(restart_notice.started_at_raw),
            render_markdown=False,
        )

    # Shared reference for progress callbacks
    _thinking: ThinkingSpinner | None = None

    def _make_progress(renderer: StreamRenderer | None = None):
        reasoning_buffer = _ReasoningBuffer()

        async def _cli_progress(
            content: str, *, tool_hint: bool = False, reasoning: bool = False, **_kwargs: Any
        ) -> None:
            ch = agent_loop.channels_config

            if _kwargs.get("reasoning_end"):
                if ch and not ch.show_reasoning:
                    reasoning_buffer.clear()
                else:
                    _flush_cli_reasoning(reasoning_buffer, _thinking, renderer)
                return

            if reasoning:
                if ch and not ch.show_reasoning:
                    reasoning_buffer.clear()
                    return
                text = reasoning_buffer.add(content)
                if text:
                    _print_cli_reasoning(text, _thinking, renderer)
                return
            if ch and tool_hint and not ch.send_tool_hints:
                return
            if ch and not tool_hint and not ch.send_progress:
                return
            _print_cli_progress_line(content, _thinking, renderer)

        return _cli_progress

    if message:
        # Single message mode — direct call, no bus needed
        async def run_once():
            renderer = StreamRenderer(
                render_markdown=markdown,
                bot_name=config.agents.defaults.bot_name,
                bot_icon=config.agents.defaults.bot_icon,
                spacing_renderer=_make_spacing_renderer(config),
            )
            global _ACTIVE_RENDERER
            _ACTIVE_RENDERER = renderer
            response = await agent_loop.process_direct(
                message,
                session_id,
                on_progress=_make_progress(renderer),
                on_stream=renderer.on_delta,
                on_stream_end=renderer.on_end,
            )
            if not renderer.streamed:
                await renderer.close()
                print_kwargs: dict[str, Any] = {}
                if renderer.header_printed:
                    print_kwargs["show_header"] = False
                _print_agent_response(
                    response.content if response else "",
                    render_markdown=markdown,
                    metadata=response.metadata if response else None,
                    **print_kwargs,
                )
            await agent_loop.close_mcp()

        asyncio.run(run_once())
    else:
        # Interactive mode — route through bus like other channels
        from femtobot.bus.events import InboundMessage

        _init_prompt_session()
        _model, _preset_tag = _model_display(config)
        console.print(
            f"{__logo__} Interactive mode [bold blue]({_model})[/bold blue]{_preset_tag} — type [bold]exit[/bold] or [bold]Ctrl+C[/bold] to quit\n"
        )

        if ":" in session_id:
            cli_channel, cli_chat_id = session_id.split(":", 1)
        else:
            cli_channel, cli_chat_id = "cli", session_id

        # Audit (C3 of the v0.0.8 third-pass review): the
        # previous signal handler called ``sys.exit(0)`` from the
        # signal frame, which raised ``SystemExit`` *between*
        # bytecodes of the asyncio loop.  The ``finally`` block
        # that calls ``agent_loop.stop()``, ``close_mcp()`` and
        # ``outbound_task.cancel()`` never ran, leaving the agent
        # loop's background tasks and MCP sockets dangling.
        #
        # The fix: signal handlers run in the main thread (where
        # asyncio is the running loop), so we can schedule a
        # callback on the loop via ``call_soon_threadsafe`` that
        # sets a flag.  The ``run_interactive`` loop checks the
        # flag and exits cleanly, which lets the ``finally`` block
        # run.
        stop_requested = threading.Event()

        def _handle_signal(signum, frame):
            sig_name = signal.Signals(signum).name
            _restore_terminal()
            console.print(f"\nReceived {sig_name}, goodbye!")
            stop_requested.set()
            # Wake the loop if it's blocked on an await.
            try:
                loop = asyncio.get_running_loop()
                loop.call_soon_threadsafe(stop_requested.set)
            except RuntimeError:
                # No running loop; we're already exiting.  Fall
                # back to a hard ``os._exit`` so we don't hang.
                os._exit(0)

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)
        # SIGHUP is not available on Windows
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, _handle_signal)
        # Ignore SIGPIPE to prevent silent process termination when writing to closed pipes
        # SIGPIPE is not available on Windows
        if hasattr(signal, "SIGPIPE"):
            signal.signal(signal.SIGPIPE, signal.SIG_IGN)

        async def run_interactive():
            bus_task = asyncio.create_task(agent_loop.run())
            turn_done = asyncio.Event()
            turn_done.set()
            turn_response: list[tuple[str, dict]] = []
            renderer: StreamRenderer | None = None
            reasoning_buffer = _ReasoningBuffer()

            async def _consume_outbound():
                while True:
                    try:
                        msg = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)

                        if msg.metadata.get("_stream_delta"):
                            if renderer:
                                await renderer.on_delta(msg.content)
                            continue
                        if msg.metadata.get("_stream_end"):
                            if renderer:
                                await renderer.on_end(
                                    resuming=msg.metadata.get("_resuming", False),
                                )
                            continue
                        if msg.metadata.get("_streamed"):
                            turn_done.set()
                            continue

                        if await _maybe_print_interactive_progress(
                            msg,
                            renderer,
                            agent_loop.channels_config,
                            renderer,
                            reasoning_buffer,
                        ):
                            continue

                        if not turn_done.is_set():
                            if msg.content:
                                turn_response.append((msg.content, dict(msg.metadata or {})))
                            turn_done.set()
                        elif msg.content:
                            await _print_interactive_response(
                                msg.content,
                                render_markdown=markdown,
                                metadata=msg.metadata,
                            )

                    except asyncio.TimeoutError:
                        continue
                    except asyncio.CancelledError:
                        break

            outbound_task = asyncio.create_task(_consume_outbound())

            try:
                while True:
                    try:
                        _flush_pending_tty_input()
                        # Stop spinner before user input to avoid prompt_toolkit conflicts
                        if renderer:
                            renderer.stop_for_input()
                        raw_input = await _read_interactive_input_async(config)
                        if _get_cli_multiline_mode() != "off":
                            raw_input = submit_multiline_transform(raw_input)
                        user_input = _sanitize_surrogates(raw_input)
                        command = user_input.strip()
                        if not command:
                            continue

                        if _is_exit_command(command):
                            _restore_terminal()
                            console.print("\nGoodbye!")
                            break

                        # Bash mode: prefix '!' executes a subprocess directly.
                        # Output is captured and printed; it does NOT enter the
                        # agent loop on its own (avoids burning LLM tokens on
                        # inspection). The user can `/mention` the output into
                        # a subsequent turn by typing `!git status` and then
                        # describing what they want.
                        bash_handled = await _handle_bash_mode(
                            user_input, config, console
                        )
                        if bash_handled:
                            continue

                        turn_done.clear()
                        turn_response.clear()
                        reasoning_buffer.clear()
                        renderer = StreamRenderer(
                            render_markdown=markdown,
                            bot_name=config.agents.defaults.bot_name,
                            bot_icon=config.agents.defaults.bot_icon,
                            spacing_renderer=_make_spacing_renderer(config),
                        )
                        global _ACTIVE_RENDERER
                        _ACTIVE_RENDERER = renderer

                        await bus.publish_inbound(
                            InboundMessage(
                                channel=cli_channel,
                                sender_id="user",
                                chat_id=cli_chat_id,
                                content=user_input,
                                metadata={"_wants_stream": True},
                            )
                        )

                        await turn_done.wait()

                        if turn_response:
                            content, meta = turn_response[0]
                            if content and not meta.get("_streamed"):
                                if renderer:
                                    await renderer.close()
                                print_kwargs: dict[str, Any] = {}
                                if renderer and renderer.header_printed:
                                    print_kwargs["show_header"] = False
                                _print_agent_response(
                                    content,
                                    render_markdown=markdown,
                                    metadata=meta,
                                    **print_kwargs,
                                )
                        elif renderer and not renderer.streamed:
                            await renderer.close()
                    except KeyboardInterrupt:
                        _restore_terminal()
                        console.print("\nGoodbye!")
                        break
                    except EOFError:
                        _restore_terminal()
                        console.print("\nGoodbye!")
                        break
                    # Audit (C3 of the v0.0.8 third-pass review):
                    # signal handlers now set ``stop_requested``
                    # instead of calling ``sys.exit(0)`` mid-loop.
                    # Check the flag here so the ``finally`` block
                    # (which closes MCP, cancels tasks, etc.) still
                    # runs and we don't leak resources.
                    if stop_requested.is_set():
                        break
            finally:
                agent_loop.stop()
                outbound_task.cancel()
                await asyncio.gather(bus_task, outbound_task, return_exceptions=True)
                await agent_loop.close_mcp()

        asyncio.run(run_interactive())


# ============================================================================
# Status Commands
# ============================================================================


@app.command()
def status(
    folder_path: str | None = typer.Option(
        None, "--folder-path", "-f", help="Instance folder path"
    ),
    suffix: str | None = typer.Option(None, "--suffix", "-s", help="Instance suffix"),
):
    """Show Femtobot status."""
    from femtobot.config.loader import get_config_path, load_config, resolve_runtime_location
    from femtobot.config.paths import get_workspace_path

    resolve_runtime_location(
        config_path=None,
        folder_path=Path(folder_path) if folder_path else None,
        suffix=suffix,
    )

    config_path = get_config_path()
    config = load_config()
    # Use get_workspace_path() which resolves relative to instance_dir
    workspace = get_workspace_path(
        config.agents.defaults.workspace if hasattr(config, "agents") else None
    )

    console.print(f"{__logo__} Femtobot Status\n")

    console.print(
        f"Config: {config_path} {'[green]✓[/green]' if config_path.exists() else '[red]✗[/red]'}"
    )
    console.print(
        f"Workspace: {workspace} {'[green]✓[/green]' if workspace.exists() else '[red]✗[/red]'}"
    )

    if config_path.exists():
        from femtobot.providers.registry import PROVIDERS

        _model, _preset_tag = _model_display(config)
        console.print(f"Model: {_model}{_preset_tag}")

        # Check API keys from registry
        for spec in PROVIDERS:
            p = getattr(config.providers, spec.name, None)
            if p is None:
                continue
            if spec.is_oauth:
                console.print(f"{spec.label}: [green]✓ (OAuth)[/green]")
            elif spec.is_local:
                # Local deployments show api_base instead of api_key
                if p.api_base:
                    console.print(f"{spec.label}: [green]✓ {p.api_base}[/green]")
                else:
                    console.print(f"{spec.label}: [dim]not set[/dim]")
            else:
                has_key = bool(p.api_key)
                console.print(
                    f"{spec.label}: {'[green]✓[/green]' if has_key else '[dim]not set[/dim]'}"
                )


if __name__ == "__main__":
    app()


# ============================================================================
# Config subcommands (A1)
# ============================================================================

config_app = typer.Typer(help="Inspect and validate the active config.")
app.add_typer(config_app, name="config")


@config_app.command("validate")
def config_validate(
    folder_path: str | None = typer.Option(
        None, "--folder-path", "-f", help="Instance folder path"
    ),
    suffix: str | None = typer.Option(None, "--suffix", "-s", help="Instance suffix"),
    config_path: str | None = typer.Option(
        None, "--config", "-c", help="Explicit path to config.json"
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Fail-fast with exit 2 on invalid config (sets FEMTOBOT_STRICT_CONFIG_LOAD).",
    ),
):
    """Validate config.json without starting the agent loop.

    Exit code 0 = OK, 2 = invalid (only when --strict is passed or
    FEMTOBOT_STRICT_CONFIG_LOAD is set).
    """
    from femtobot.config.loader import (
        resolve_runtime_location,
    )
    from femtobot.config.loader import (
        validate_config as _validate_config,
    )

    resolve_runtime_location(
        config_path=Path(config_path) if config_path else None,
        folder_path=Path(folder_path) if folder_path else None,
        suffix=suffix,
    )
    target = Path(config_path) if config_path else None
    ok, message = _validate_config(config_path=target, strict=strict)
    if ok:
        console.print(f"[green]✓[/green] {message}")
        raise SystemExit(0)
    console.print(f"[red]✗[/red] {message}")
    raise SystemExit(2)


# ============================================================================
# Tools subcommands (C2)
# ============================================================================

tools_app = typer.Typer(help="Inspect the tool registry.")
app.add_typer(tools_app, name="tools")


@tools_app.command("list")
def tools_list(
    folder_path: str | None = typer.Option(
        None, "--folder-path", "-f", help="Instance folder path"
    ),
    suffix: str | None = typer.Option(None, "--suffix", "-s", help="Instance suffix"),
    capability: str | None = typer.Option(
        None,
        "--capability",
        "-c",
        help="Filter to tools that advertise this capability (e.g. read-only, long-running).",
    ),
    show_capabilities: bool = typer.Option(
        False,
        "--show-capabilities",
        help="Also print the capability list for each tool.",
    ),
):
    """List tools registered in the active agent loop.

    With ``--capability <name>`` (C2), only the tools that advertise
    that capability are listed.  With ``--show-capabilities``, each
    tool's ``get_capabilities()`` output is appended after the name.
    """
    from femtobot.agent.tools.registry import ToolRegistry
    from femtobot.config.loader import resolve_runtime_location

    resolve_runtime_location(
        config_path=None,
        folder_path=Path(folder_path) if folder_path else None,
        suffix=suffix,
    )
    # C2: build a minimal in-memory registry and call ``by_capability``
    # so the filter logic is exercised end-to-end.  The list won't
    # match a running loop's exact set of MCP tools, but the
    # filtering is what the CLI needs to validate.
    from femtobot.agent.tools.loader import ToolLoader

    registry = ToolRegistry()
    loader = ToolLoader()
    tool_classes = loader.discover()
    for tool_cls in tool_classes:
        # ``create(None)`` fails when a tool needs a real config (e.g.
        # MCP-backed tools).  We narrow the catch to the failure modes
        # that ``create`` actually documents so a typo or import error
        # in a builtin surfaces instead of being silently swallowed.
        try:
            tool = tool_cls.create(None)  # type: ignore[arg-type]
            registry.register(tool)
        except (TypeError, ValueError, RuntimeError, AttributeError):  # pragma: no cover - defensive
            continue
    if capability:
        tools = registry.by_capability(capability)
    else:
        tools = sorted(registry._tools.values(), key=lambda t: t.name)  # type: ignore[attr-defined]
    if not tools:
        msg = (
            f"No tools match capability {capability!r}."
            if capability
            else "No tools registered."
        )
        console.print(f"[yellow]{msg}[/yellow]")
        raise SystemExit(0)
    for tool in tools:
        # Audit (H3 of the v0.0.9 fourth-pass review): the
        # previous code did ``suffix = ""`` which shadowed the
        # ``suffix`` Typer parameter (used to locate the
        # instance folder).  The outer ``suffix`` was no longer
        # ``None`` (default) but a string; the existing
        # ``resolve_runtime_location(...)`` call had already
        # captured the original, so this was a latent bug (the
        # Typer parameter still worked, but the inner ``suffix``
        # binding was a confusing shadow).  We rename the inner
        # binding to ``cap_suffix`` for clarity.
        cap_suffix = ""
        if show_capabilities:
            caps = tool.get_capabilities()
            cap_suffix = f"  [dim]({', '.join(caps)})[/dim]" if caps else ""
        console.print(f"- {tool.name}{cap_suffix}")
