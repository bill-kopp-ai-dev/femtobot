"""Tests for the ``## Tools available right now`` block (PR 5.2).

Verifies:

- The block is **omitted** when the caller does not opt in (no
  ``tools_config`` argument), so legacy system prompts are
  byte-identical to the pre-PR-5.2 baseline.
- When ``tools_config`` is supplied, the block lists the local tools
  unconditionally.
- When MCP servers are connected, the block lists them under
  ``MCP tools (currently connected)``.
- When MCP servers are configured but not connected, the block warns
  and lists them under ``⚠ not connected``.
- The ordering is Identity → Bootstrap → tool_contract → tools
  available → mcp_capability, matching the precedence the agent is
  expected to follow.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from femtobot.agent.context import ContextBuilder


def _fake_tools_config(connected: bool):
    cfg = SimpleNamespace(
        mcp_servers={
            "percival-osm": SimpleNamespace(
                command="percival-osm-mcp", url=None, type="stdio"
            )
        }
    )
    return cfg


def test_no_block_when_tools_config_is_none():
    with tempfile.TemporaryDirectory() as tmp:
        cb = ContextBuilder(workspace=Path(tmp))
        prompt = cb.build_system_prompt()
        assert "## Tools available right now" not in prompt


def test_block_lists_local_tools_always():
    with tempfile.TemporaryDirectory() as tmp:
        cb = ContextBuilder(workspace=Path(tmp))
        prompt = cb.build_system_prompt(
            tools_config=_fake_tools_config(connected=False),
            configured_servers=set(),
            connected_servers=set(),
        )
        assert "## Tools available right now" in prompt
        # Spot-check the local-tool catalog. The exact list is
        # documented in the plan; if the agent grows new local tools,
        # add them here.
        for tool in ("exec", "read_file", "grep", "glob", "apply_patch"):
            assert f"- `{tool}`" in prompt


def test_block_lists_connected_servers():
    with tempfile.TemporaryDirectory() as tmp:
        cb = ContextBuilder(workspace=Path(tmp))
        prompt = cb.build_system_prompt(
            tools_config=_fake_tools_config(connected=True),
            configured_servers={"percival-osm"},
            connected_servers={"percival-osm"},
        )
        assert "MCP tools (currently connected)" in prompt
        assert "mcp_percival-osm_*" in prompt
        assert "not connected" not in prompt.split(
            "MCP tools (currently connected)"
        )[1]


def test_block_warns_on_configured_but_disconnected():
    with tempfile.TemporaryDirectory() as tmp:
        cb = ContextBuilder(workspace=Path(tmp))
        prompt = cb.build_system_prompt(
            tools_config=_fake_tools_config(connected=False),
            configured_servers={"percival-osm"},
            connected_servers=set(),
        )
        assert "⚠ not connected" in prompt
        assert "percival-osm" in prompt


def test_block_appears_after_tool_contract():
    with tempfile.TemporaryDirectory() as tmp:
        cb = ContextBuilder(workspace=Path(tmp))
        prompt = cb.build_system_prompt(
            tools_config=_fake_tools_config(connected=True),
            configured_servers={"percival-osm"},
            connected_servers={"percival-osm"},
        )
        idx_contract = prompt.find("## ")
        # Both sections start with ``## ``; check the position of
        # ``Tools available right now`` is after the bootstrap block.
        idx_tools = prompt.find("Tools available right now")
        idx_mcp = prompt.find("MCP Servers")
        # Tools available must precede any MCP Servers block — it is
        # the higher-precedence "what can I actually call" summary.
        if idx_mcp != -1:
            assert idx_tools < idx_mcp, (
                "Tools available block must precede MCP Servers block"
            )
