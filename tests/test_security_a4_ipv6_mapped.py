"""Security regression tests for IPv6-mapped IPv4 SSRF bypass (A4).

The SSRF guard used to rely solely on Python's ipaddress containment, which
treats ``::ffff:127.0.0.1`` as an IPv6 address *outside* the IPv4
``127.0.0.0/8`` block.  ``_normalize_addr`` converts it back to IPv4
before the blocklist check, but a regression in the normalize step (or a
call site that forgets to invoke it) would unblock the bypass.

A4 (REFACTOR_PLAN.md Lote A) added ``::ffff:0:0/96`` to the blocklist as
defense-in-depth, so even if a future refactor regresses the normalize
step the literal IPv6-mapped range is still blocked.
"""

from __future__ import annotations

import pytest

from femtobot.security.network import (
    _BLOCKED_NETWORKS,
    _normalize_addr,
    validate_resolved_url,
    validate_url_target,
)

pytestmark = pytest.mark.security


def test_ipv6_mapped_range_in_blocklist() -> None:
    """The IPv6-mapped IPv4 range is in _BLOCKED_NETWORKS explicitly (A4)."""
    from ipaddress import ip_network

    assert ip_network("::ffff:0:0/96") in _BLOCKED_NETWORKS


def test_ipv6_mapped_loopback_blocked() -> None:
    """``http://[::ffff:127.0.0.1]/`` is rejected even with allow_loopback."""
    ok, msg = validate_url_target("http://[::ffff:127.0.0.1]/")
    assert not ok, f"Expected block, got ok=True (msg={msg!r})"
    assert "private" in msg.lower() or "blocked" in msg.lower()


def test_ipv6_mapped_metadata_blocked() -> None:
    """``http://[::ffff:169.254.169.254]/`` is rejected (EC2 metadata)."""
    ok, msg = validate_url_target("http://[::ffff:169.254.169.254]/latest/meta-data/")
    assert not ok
    assert "private" in msg.lower() or "blocked" in msg.lower()


def test_ipv6_mapped_rfc1918_blocked() -> None:
    """``http://[::ffff:10.0.0.1]/`` is rejected (RFC1918 mapped to v6)."""
    ok, msg = validate_url_target("http://[::ffff:10.0.0.1]/admin")
    assert not ok


def test_normalize_strips_ipv6_mapped_prefix() -> None:
    """``_normalize_addr`` converts ``::ffff:127.0.0.1`` to its IPv4 form."""
    import ipaddress

    addr = ipaddress.ip_address("::ffff:127.0.0.1")
    normalized = _normalize_addr(addr)
    assert isinstance(normalized, ipaddress.IPv4Address)
    assert str(normalized) == "127.0.0.1"


def test_validate_resolved_url_still_rejects_ipv6_mapped() -> None:
    """The post-redirect checker also rejects IPv6-mapped addresses (A4)."""
    ok, msg = validate_resolved_url("http://[::ffff:127.0.0.1]:8080/")
    assert not ok
