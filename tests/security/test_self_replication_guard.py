"""Verify Femtobot cannot self-replicate via the ``exec`` tool.

longlogs.txt 2026-07-15 15:53: a ``.femtobot_ok/`` instance was created
on disk while the operator was away — most likely via ``femtobot
onboard --suffix ok`` invoked through the agent's ``exec`` tool. Block
that at the command-safety layer so the agent cannot bootstrap siblings.

After R2-femtobot (refactor-parity-with-nanobot.md Phase 1) the
``--suffix`` flag was removed entirely, so the original attack vector
(femtobot onboard --suffix ok) is no longer reachable from the CLI.
The legacy tests below remain as defence-in-depth — the regex
``\\bfemtobot\\b[^|;&<>]*\\b(onboard|init|new)\\b`` still matches any
invocation that looks like a Femtobot bootstrap (e.g. a hand-rolled
script named ``femtobot``, a shim, or a wrapper).  The new tests
(``test_phase2_*``) cover the actual post-Phase-1 vectors: copying
the existing ``.femtobot/`` directory and rewriting ``config.json``.
"""
import pytest

from femtobot.security.command_guard import check_command_safety


def test_femtobot_onboard_blocked():
    """Legacy: even though ``--suffix`` was removed, any
    ``femtobot onboard ...`` invocation must remain blocked."""
    ok, reason = check_command_safety(
        "femtobot onboard",
        workspace_root=None,
    )
    assert ok is False, "femtobot onboard must be blocked"
    assert "deny pattern" in reason.lower() or "blocked" in reason.lower()


def test_femtobot_init_blocked():
    """Legacy: ``femtobot init ...`` is still in the deny list."""
    ok, reason = check_command_safety(
        "femtobot init dev",
        workspace_root=None,
    )
    assert ok is False


def test_femtobot_new_blocked():
    """Legacy: ``femtobot new my-instance`` is still in the deny list."""
    ok, reason = check_command_safety(
        "femtobot new my-instance",
        workspace_root=None,
    )
    assert ok is False


def test_ls_still_allowed():
    """Sanity: ordinary inspection commands must still pass."""
    ok, _ = check_command_safety(
        "ls -la .femtobot/",
        workspace_root=None,
    )
    assert ok is True, "ls must remain allowed"


def test_user_can_override_with_allow_patterns():
    """Operators who really want this can opt in via allow_patterns."""
    ok, _ = check_command_safety(
        "femtobot onboard",
        workspace_root=None,
        allow_patterns=[r"femtobot\s+onboard"],
    )
    assert ok is True, "explicit allow_patterns must override deny"


# R2-femtobot (refactor-parity-with-nanobot.md Phase 2): even after the
# ``--suffix`` flag was dropped, the agent can still materialise a sibling
# ``.femtobot`` directory by (a) recursively copying the existing one, or
# (b) writing into the instance ``config.json``.  These patterns cover
# those vectors as defence in depth.

_BLOCKED = [
    # Direct copy / move / rsync of the .femtobot directory
    "cp -r .femtobot /tmp/femtobot_clone",
    "cp -a .femtobot /tmp/clone",
    "rsync -a .femtobot/ /tmp/x/",
    "mv .femtobot /tmp/x",
    "cp -r .femtobot /tmp/.femtobot_clone",
    # Absolute source path
    "cp -r /opt/myproj/.femtobot /tmp/clone",
    # Config.json write vectors
    "echo {} > .femtobot/config.json",
    "echo foo >> .femtobot/config.json",
    "tee /tmp/x.json < .femtobot/config.json",
    "sed -i s/x/y/g .femtobot/config.json",
    "dd if=/dev/zero of=.femtobot/config.json bs=1k count=1",
    "mv .femtobot/config.json /tmp/foo.json",
    "cp .femtobot/config.json /tmp/foo.json",
    # Archive-based exfiltration (review feedback R2-femtobot)
    "tar czf /tmp/x.tar.gz .femtobot",
    "tar czf /tmp/x.tar.gz -C /opt/proj .femtobot",
    "tar xzf backup.tar.gz -C .femtobot",
    "zip -r /tmp/x.zip .femtobot",
    # Python-driven bypasses (review feedback R2-femtobot)
    'python3 -c "import shutil; shutil.copytree(\'.femtobot\', \'/tmp/x\')"',
    'python -c "import os; os.chdir(\'.femtobot\')"',
    'python -c "import shutil; rmtree(\'.femtobot\')"',
]

_ALLOWED = [
    # Ordinary inspection / read of the instance must keep working.
    "cp /etc/hosts /tmp/x",
    "ls -la .femtobot/",
    "ls -la .femtobot/workspace/skills",
    "cat .femtobot/config.json",
    "cat .femtobot/workspace/SOUL.md",
    # Writes to other config.json paths must be unaffected.
    "echo {} > /tmp/config.json",
    "echo {} > /tmp/config.jsonl",
    # Other source paths
    "rsync -a /home/bill/Codes/agents /tmp/x",
    "femtobot status",
    "femtobot agent -m hello",
    # Unrelated names that *contain* ".femtobot" as a substring must
    # not trigger the guard — only the literal instance directory does.
    "cat .nanobot_ok_history.txt",
    "mkdir -p /tmp/workdir",
    "cp -r .femtobot_ok_history /tmp/x",
    # Archive commands on unrelated paths.
    "tar czf backup.tar.gz workspace",
    "tar xzf project.tar.gz",
    "zip -r /tmp/x.zip /opt/myapp",
    # Ordinary Python one-liners must not be blocked.
    'python3 -c "print(1+1)"',
    'python -c "import sys; sys.exit(0)"',
    "python3 -m pip install requests",
    'python -c "x = 1; y = 2; print(x+y)"',
]


@pytest.mark.parametrize("cmd", _BLOCKED)
def test_phase2_clone_blocked(cmd: str) -> None:
    ok, _ = check_command_safety(cmd, workspace_root=None)
    assert ok is False, f"must block self-replication attempt: {cmd}"


@pytest.mark.parametrize("cmd", _ALLOWED)
def test_phase2_unrelated_commands_still_allowed(cmd: str) -> None:
    ok, reason = check_command_safety(cmd, workspace_root=None)
    assert ok is True, f"must allow unrelated command ({reason}): {cmd}"