"""Voice input for the Femtobot CLI via system microphone + Whisper transcription.

Inspired by Claude Code Voice:
FEMTOBOT_CLI_REFACTOR_PLAN.md Camada 3, T3.3.

MVP behaviour:
  1. User presses Alt+V (configurable keybind)
  2. CLI shows "Recording..." indicator
  3. Audio is captured via arecord (Linux) / sox / ffmpeg
  4. Audio is saved to a temp WAV file
  5. The temp file is sent to GroqTranscriptionProvider (already exists)
  6. Transcribed text is inserted into the input buffer
  7. User edits or submits as usual

Security: audio is NEVER saved permanently. Temp file is deleted after use.

Dependencies:
  - Linux: arecord (alsa-utils) or ffmpeg
  - macOS: ffmpeg / sox
  - Windows: ffmpeg

Config:
  voiceEnabled: bool (default False)
  voiceKey: str (default "alt-v")
  voiceTimeout: float (default 30.0 seconds)
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT_S = 30.0


@dataclass
class VoiceConfig:
    """Configuration for voice input."""
    enabled: bool = False
    keybind: str = "alt-v"  # key that triggers recording
    timeout_s: float = DEFAULT_TIMEOUT_S
    sample_rate: int = 16000
    channels: int = 1


async def _detect_audio_recorder() -> str | None:
    """Find the best available audio recorder on this system.

    Audit (C4 of the v0.0.8 third-pass review): this function used
    to call ``subprocess.run`` synchronously.  When called from an
    async coroutine (``record_audio``), it blocked the event loop
    for up to 5 seconds per ``which`` invocation, totalling up to
    15 seconds.  The caller is now expected to ``await`` this
    function; we offload to a thread so the loop stays responsive.
    """
    for cmd in ["ffmpeg", "arecord", "sox"]:
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["which", cmd],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return cmd
        except Exception:
            pass
    return None


async def record_audio(
    config: VoiceConfig,
    output_path: Path,
    *,
    on_duration: asyncio.AbstractEventLoop | None = None,
) -> bool:
    """Record audio from the system microphone to output_path (WAV format).

    Returns True if recording succeeded, False otherwise.
    Deletes output_path on failure.
    """
    recorder = await _detect_audio_recorder()
    if recorder is None:
        return False

    cmd: list[str]
    if recorder == "ffmpeg":
        if sys.platform == "darwin":
            input_args = ["-f", "avfoundation", "-i", ":0"]
        elif sys.platform == "win32":
            input_args = ["-f", "dshow", "-i", "audio=Microphone"]
        else:
            input_args = ["-f", "alsa", "-i", "default"]
        cmd = [
            recorder,
            *input_args,
            "-ar", str(config.sample_rate),
            "-ac", str(config.channels),
            "-t", str(config.timeout_s),
            "-y",                   # overwrite output
            str(output_path),
        ]
    elif recorder == "arecord":
        cmd = [
            recorder,
            "-f", "cd",             # 16-bit, 44100 Hz, stereo
            "-r", str(config.sample_rate),
            "-c", str(config.channels),
            "-d", str(int(config.timeout_s)),
            "-N",                   # non-blocking
            str(output_path),
        ]
    else:  # sox
        cmd = [
            recorder, "rec",
            str(output_path),
            "rate", str(config.sample_rate),
            "channels", str(config.channels),
            "trim", "0", str(config.timeout_s),
        ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.communicate(), timeout=config.timeout_s + 2)
        return output_path.exists() and output_path.stat().st_size > 0
    except Exception:
        try:
            output_path.unlink(missing_ok=True)
        except OSError:
            pass
        return False


async def transcribe_audio(
    audio_path: Path,
    transcription_provider: object,
) -> str:
    """Send audio to the transcription provider and return the text.

    ``transcription_provider`` must implement:
        async def transcribe(audio_path: Path) -> str

    The Femtobot GroqTranscriptionProvider (femtobot/providers/transcription.py)
    satisfies this interface.
    """
    transcribe_fn = getattr(transcription_provider, "transcribe", None)
    if transcribe_fn is None:
        return ""
    try:
        result = await transcribe_fn(audio_path)
        if isinstance(result, str):
            return result.strip()
        if isinstance(result, dict):
            return str(result.get("text", "")).strip()
        return str(result).strip()
    except Exception:
        return ""


def cleanup_audio(audio_path: Path) -> None:
    """Delete the temporary audio file. Safe to call even if file doesn't exist."""
    try:
        audio_path.unlink(missing_ok=True)
    except OSError:
        pass
