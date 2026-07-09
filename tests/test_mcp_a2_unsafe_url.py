"""MCP startup pre-flight SSRF guard (A2).

Before A2 the MCP HTTP transports would TCP-probe any URL configured in
``mcp_servers.*.url`` and then connect to it, with no SSRF guard at all.
A malicious or accidental ``http://169.254.169.254/...`` config could talk
to the cloud metadata service before any policy could stop it.

A2 (REFACTOR_PLAN.md Lote A) introduces ``_preflight_check_mcp_url``,
which calls the same ``validate_url_target`` used by ``web_fetch`` before
the probe runs.  Rejecting here means the transport never even gets to
the open_connection call.
"""

from __future__ import annotations

import pytest

from femtobot.agent.tools.mcp import _preflight_check_mcp_url

pytestmark = pytest.mark.security


def test_preflight_blocks_ec2_metadata() -> None:
    """``http://169.254.169.254/`` is rejected before the probe (A2)."""
    ok, msg = _preflight_check_mcp_url("http://169.254.169.254/latest/meta-data/")
    assert not ok
    assert "private" in msg.lower() or "blocked" in msg.lower()


def test_preflight_blocks_rfc1918() -> None:
    """Internal RFC1918 endpoints are rejected (A2)."""
    ok, msg = _preflight_check_mcp_url("http://10.0.0.5:8080/mcp")
    assert not ok


def test_preflight_blocks_ipv6_mapped_metadata() -> None:
    """IPv6-mapped metadata is also rejected (A2 + A4)."""
    ok, msg = _preflight_check_mcp_url("http://[::ffff:169.254.169.254]/")
    assert not ok


def test_preflight_allows_loopback() -> None:
    """Localhost MCP servers are allowed (typical use case)."""
    ok, _msg = _preflight_check_mcp_url("http://127.0.0.1:8765/mcp")
    assert ok


def test_preflight_allows_localhost_named() -> None:
    """``localhost`` is allowed even without an explicit loopback IP."""
    ok, _msg = _preflight_check_mcp_url("http://localhost:8765/mcp")
    assert ok


def test_preflight_rejects_non_http_scheme() -> None:
    """Only http/https is accepted; file://, gopher://, etc. are rejected."""
    ok, msg = _preflight_check_mcp_url("file:///etc/passwd")
    assert not ok


def test_preflight_rejects_empty_url() -> None:
    """An empty URL is rejected with a clear message."""
    ok, msg = _preflight_check_mcp_url("")
    assert not ok
    assert "missing" in msg.lower()
