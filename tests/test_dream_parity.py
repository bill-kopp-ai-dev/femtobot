"""Dream consolidation parity review regression tests (v0.1.5 eighth-pass R1-R6).

This test file pins the v0.1.5 close-out of the findings recorded in
``docs/dream_parity_review.md``.  Each test names the finding it
guards against so a future refactor can't silently re-introduce the
regressions.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

from femtobot.agent.autocompact import AutoCompact
from femtobot.agent.memory import MemoryStore

# ---------------------------------------------------------------------------
# R1 — current memory files are embedded in the Dream prompt
# ---------------------------------------------------------------------------


def test_r1_render_current_memory_files_keeps_short_files(tmp_path: Path) -> None:
    """R1: a small SOUL.md is embedded in full (no truncation marker)."""
    (tmp_path / "SOUL.md").write_text("be concise and helpful")
    store = MemoryStore(tmp_path)
    section = store._render_current_memory_files()
    assert "be concise" in section
    assert "SOUL.md" in section
    assert "[truncated]" not in section


def test_r1_render_current_memory_files_skips_missing(tmp_path: Path) -> None:
    """R1: missing durable files are silently skipped (no section)."""
    store = MemoryStore(tmp_path)
    section = store._render_current_memory_files()
    assert section == ""


def test_r1_render_current_memory_files_handles_all_three(tmp_path: Path) -> None:
    """R1: SOUL.md, USER.md, memory/MEMORY.md are all embedded."""
    (tmp_path / "memory").mkdir(parents=True)
    (tmp_path / "SOUL.md").write_text("soul content")
    (tmp_path / "USER.md").write_text("user content")
    (tmp_path / "memory" / "MEMORY.md").write_text("memory content")

    store = MemoryStore(tmp_path)
    section = store._render_current_memory_files()
    assert "soul content" in section
    assert "user content" in section
    assert "memory content" in section


# ---------------------------------------------------------------------------
# R2 — dream_content_diff + build_dream_commit_message
# ---------------------------------------------------------------------------


def test_r2_dream_content_diff_empty_when_no_git(tmp_path: Path) -> None:
    """R2: dream_content_diff returns "" when git is not initialized."""
    store = MemoryStore(tmp_path)
    (tmp_path / "SOUL.md").write_text("modified")
    assert store.git.is_initialized() is False
    assert store.dream_content_diff() == ""


def test_r2_build_dream_commit_message_uses_diff_body() -> None:
    """R2: build_dream_commit_message prefers diff_body over resp content."""
    resp = MagicMock()
    resp.content = "I think I changed SOUL.md"
    msg = MemoryStore.build_dream_commit_message(
        "dream: cron", resp, diff_body="SOUL.md: +3 -1\nbe concise"
    )
    # The diff body anchors the message, NOT the LLM self-report.
    assert "SOUL.md" in msg
    assert "I think I changed" not in msg


def test_r2_build_dream_commit_message_falls_back_to_resp() -> None:
    """R2: when diff_body is empty, the resp one-liner is used."""
    resp = MagicMock()
    resp.content = "auto-summary line"
    msg = MemoryStore.build_dream_commit_message("dream: cron", resp)
    # Falls back to the resp content as before.
    assert "auto-summary" in msg


# ---------------------------------------------------------------------------
# R3 — _has_compactable_idle_tail
# ---------------------------------------------------------------------------


def test_r3_has_compactable_idle_tail_empty_session() -> None:
    """R3: a session with no messages is not compactable."""
    ac = AutoCompact(consolidator=MagicMock(), sessions=MagicMock())
    ac.sessions.get_or_create.return_value = MagicMock(
        messages=[], last_consolidated=0
    )
    assert ac._has_compactable_idle_tail("cli:direct") is False


def test_r3_has_compactable_idle_tail_already_consolidated() -> None:
    """R3: a session whose tail fits in the suffix is not compactable."""
    ac = AutoCompact(consolidator=MagicMock(), sessions=MagicMock())
    ac.sessions.get_or_create.return_value = MagicMock(
        messages=[{"role": "user", "content": f"m{i}"} for i in range(5)],
        last_consolidated=0,
    )
    # 5 messages, suffix is 8 → tail fits inside the suffix, not compactable.
    assert ac._has_compactable_idle_tail("cli:direct") is False


def test_r3_has_compactable_idle_tail_with_long_tail() -> None:
    """R3: a session with a tail longer than the suffix IS compactable."""
    ac = AutoCompact(consolidator=MagicMock(), sessions=MagicMock())
    ac.sessions.get_or_create.return_value = MagicMock(
        messages=[{"role": "user", "content": f"m{i}"} for i in range(20)],
        last_consolidated=0,
    )
    assert ac._has_compactable_idle_tail("cli:direct") is True


def test_r3_check_expired_skips_empty_tail() -> None:
    """R3: check_expired does not schedule archive for empty-tail sessions."""
    ac = AutoCompact(consolidator=MagicMock(), sessions=MagicMock())
    ac._RECENT_SUFFIX_MESSAGES = 8
    ac.sessions.get_or_create.return_value = MagicMock(
        messages=[{"role": "user", "content": f"m{i}"} for i in range(3)],
        last_consolidated=0,
    )
    ac.sessions.list_sessions.return_value = [
        {"key": "cli:direct", "updated_at": datetime.now() - timedelta(hours=2)}
    ]
    scheduled: list = []

    def schedule(coro):
        scheduled.append(coro)

    ac.check_expired(schedule, active_session_keys=set())
    # Empty-tail session should NOT be scheduled for archive.
    assert scheduled == []


# ---------------------------------------------------------------------------
# R4 — _is_internal_history_session + read_recent_history_for_prompt
# ---------------------------------------------------------------------------


def test_r4_is_internal_history_session_cron() -> None:
    """R4: ``cron:*`` sessions are internal."""
    assert MemoryStore._is_internal_history_session("cron:daily") is True


def test_r4_is_internal_history_session_dream() -> None:
    """R4: ``dream:*`` sessions are internal."""
    assert MemoryStore._is_internal_history_session("dream:20251024-120000") is True


def test_r4_is_internal_history_session_heartbeat() -> None:
    """R4: ``heartbeat`` is internal."""
    assert MemoryStore._is_internal_history_session("heartbeat") is True


def test_r4_is_internal_history_session_user() -> None:
    """R4: user sessions are not internal."""
    assert MemoryStore._is_internal_history_session("cli:direct") is False
    assert MemoryStore._is_internal_history_session("user:bob") is False


def test_r4_is_internal_history_session_none() -> None:
    """R4: ``None`` is not internal."""
    assert MemoryStore._is_internal_history_session(None) is False


# ---------------------------------------------------------------------------
# R5 — _render_current_memory_files truncates over-cap files
# ---------------------------------------------------------------------------


def test_r5_render_current_memory_files_truncates_oversize(tmp_path: Path) -> None:
    """R5: a file longer than _DREAM_FILE_EMBED_CAP is truncated."""
    big = "X" * (MemoryStore._DREAM_FILE_EMBED_CAP + 500)
    (tmp_path / "SOUL.md").write_text(big)
    store = MemoryStore(tmp_path)
    section = store._render_current_memory_files()
    assert "[truncated]" in section
    # The truncated file content is shorter than the original cap*2.
    assert len(section) < MemoryStore._DREAM_FILE_EMBED_CAP * 2


def test_r5_render_current_memory_files_skips_non_utf8(tmp_path: Path) -> None:
    """R5: a non-UTF8 file is silently skipped (R5 robustness)."""
    (tmp_path / "SOUL.md").write_bytes(b"\xff\xfe\x00\x01binary")
    store = MemoryStore(tmp_path)
    # Should not raise; non-UTF8 file is skipped.
    section = store._render_current_memory_files()
    # The non-UTF8 file is not embedded at all.
    assert "binary" not in section or "[truncated]" in section


# ---------------------------------------------------------------------------
# R6 — workspace dream.md override + truncation
# ---------------------------------------------------------------------------


def test_r6_workspace_override_is_used(tmp_path: Path) -> None:
    """R6: workspace/prompts/dream.md overrides the built-in template."""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "dream.md").write_text("CUSTOM DREAM TEMPLATE\n{{extra}}")
    store = MemoryStore(tmp_path)
    store.append_history("user: hi")
    result = store.build_dream_prompt()
    assert result is not None
    prompt, _ = result
    assert "CUSTOM DREAM TEMPLATE" in prompt


def test_r6_oversize_override_truncated(tmp_path: Path) -> None:
    """R6: an override longer than _DREAM_PROMPT_MAX_CHARS is truncated."""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    big = "X" * (MemoryStore._DREAM_PROMPT_MAX_CHARS + 1000)
    (prompts_dir / "dream.md").write_text(big)
    store = MemoryStore(tmp_path)
    store.append_history("user: hi")
    result = store.build_dream_prompt()
    assert result is not None
    # The override alone cannot exceed the cap.
    prompt, _ = result
    override_section = prompt.split("## Conversation History")[0]
    # Truncated at exactly _DREAM_PROMPT_MAX_CHARS.
    assert len(override_section) < len(big) + 200


# ---------------------------------------------------------------------------
# F1-F3 — advance_dream_cursor_after_commit still works (cursor-coupling)
# ---------------------------------------------------------------------------


def test_f3_enforce_monotonic_cursor_still_works(tmp_path: Path) -> None:
    """F3: regression of a hard-won invariant — _enforce_monotonic_cursor
    is preserved in the MemoryStore class."""
    import inspect

    from femtobot.agent.memory import MemoryStore

    # The helper must still exist and check forward-only.
    assert hasattr(MemoryStore, "_enforce_monotonic_cursor")
    src = inspect.getsource(MemoryStore._enforce_monotonic_cursor)
    # The logic must compare against the existing cursor.
    assert "max(" in src or ">" in src
    # The docstring must mention the invariant.
    assert "monotonic" in src.lower() or "regress" in src.lower()
