"""D3: Disable proxy for local endpoints (D3).

D3 (REFACTOR_PLAN.md Lote D): when ``apiBase`` is a loopback / local
hostname (``localhost``, ``127.0.0.1``, ``::1``), the OpenAI-compat
provider must build its ``httpx.AsyncClient`` with ``trust_env=False``
so ``HTTPS_PROXY`` / ``HTTP_PROXY`` from the process env don't try
to route local traffic through a corporate proxy.

The decision is recorded via the underlying ``httpx.AsyncClient``'s
``trust_env`` attribute — we test that directly without spinning up
a real request.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.providers


@pytest.fixture(autouse=True)
def _import_async_openai() -> None:
    """Force-import ``AsyncOpenAI`` so ``_build_client`` can use it (D3)."""
    # The OpenAI SDK is imported lazily by the provider to keep startup
    # fast.  Tests that drive ``_build_client`` directly need it
    # imported, so do it once at the top of the session.
    from openai import AsyncOpenAI  # noqa: F401  pylint: disable=import-outside-toplevel

    import femtobot.providers.openai_compat_provider as mod  # noqa: F401

    mod.AsyncOpenAI = AsyncOpenAI


from femtobot.providers.openai_compat_provider import OpenAICompatProvider  # noqa: E402


def _build_provider(api_base: str) -> OpenAICompatProvider:
    """Build a provider without constructing the OpenAI client.

    We bypass ``__init__`` and assign just enough state to exercise
    ``_build_client``.  The OpenAI client itself is then built in
    isolation, so we can inspect the underlying ``httpx.AsyncClient``.
    """
    provider = OpenAICompatProvider.__new__(OpenAICompatProvider)  # type: ignore[call-arg]
    # Wire the minimum state ``_build_client`` reads.
    provider._is_local = True  # type: ignore[attr-defined]
    provider._api_key_for_client = "no-key"  # type: ignore[attr-defined]
    provider._effective_base = api_base  # type: ignore[attr-defined]
    provider._default_headers = {}  # type: ignore[attr-defined]
    provider._client = None  # type: ignore[attr-defined]
    return provider


def test_local_endpoint_disables_trust_env() -> None:
    """D3: local endpoint → ``trust_env=False`` (D3)."""
    provider = _build_provider("http://127.0.0.1:11434/v1")
    provider._build_client()
    http_client = provider._client._client  # type: ignore[attr-defined]
    assert http_client.trust_env is False


def test_local_endpoint_via_localhost_disables_trust_env() -> None:
    """D3: ``localhost``-named endpoint also disables proxy (D3)."""
    provider = _build_provider("http://localhost:11434/v1")
    provider._build_client()
    http_client = provider._client._client  # type: ignore[attr-defined]
    assert http_client.trust_env is False


def test_non_local_endpoint_keeps_trust_env_default() -> None:
    """D3: a cloud endpoint does not override the trust_env default (D3)."""
    provider = OpenAICompatProvider.__new__(OpenAICompatProvider)  # type: ignore[call-arg]
    provider._is_local = False  # type: ignore[attr-defined]
    provider._api_key_for_client = "sk-test"  # type: ignore[attr-defined]
    provider._effective_base = "https://api.openai.com/v1"  # type: ignore[attr-defined]
    provider._default_headers = {}  # type: ignore[attr-defined]
    provider._client = None  # type: ignore[attr-defined]
    # _is_local=False means no http_client override — the SDK uses its
    # default httpx client, whose trust_env is True (httpx default).
    provider._build_client()
    http_client = provider._client._client  # type: ignore[attr-defined]
    assert http_client.trust_env is True


def test_https_proxy_env_does_not_affect_local_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """D3: with ``HTTPS_PROXY`` set, a local client must still go direct (D3)."""
    monkeypatch.setenv("HTTPS_PROXY", "http://corp-proxy:8080")
    monkeypatch.setenv("HTTP_PROXY", "http://corp-proxy:8080")
    provider = _build_provider("http://127.0.0.1:11434/v1")
    provider._build_client()
    http_client = provider._client._client  # type: ignore[attr-defined]
    # trust_env=False means httpx ignores HTTPS_PROXY for the local client.
    assert http_client.trust_env is False
    # And the URL doesn't get rewritten by an env-based proxy.
    # (httpx doesn't expose a "resolved proxy" attribute, but trust_env
    # is the public flag — if it's False, the env-based proxy can't
    # be applied.)


def test_https_local_keeps_trust_env_for_certs() -> None:
    """D3 (refined): ``https://127.0.0.1`` keeps ``trust_env=True`` (D3).

    Refinement of the original D3: a local HTTPS endpoint with
    self-signed certs still needs ``SSL_CERT_FILE`` / ``SSL_CERT_DIR``
    from the env.  The proxy bypass is only relevant for plain HTTP,
    so we narrow ``trust_env=False`` to ``http://`` schemes.  HTTPS
    local endpoints inherit httpx's default ``trust_env=True``.
    """
    provider = _build_provider("https://127.0.0.1:8443/v1")
    provider._build_client()
    http_client = provider._client._client  # type: ignore[attr-defined]
    # https://127.0.0.1 keeps the default so SSL_CERT_FILE still works.
    assert http_client.trust_env is True


def test_http_local_uses_trust_env_false() -> None:
    """D3: an ``http://``-only local endpoint explicitly opts out of env (D3)."""
    provider = _build_provider("http://localhost:1234/v1")
    provider._build_client()
    http_client = provider._client._client  # type: ignore[attr-defined]
    # http:// localhost falls under the proxy-bypass branch.
    assert http_client.trust_env is False
