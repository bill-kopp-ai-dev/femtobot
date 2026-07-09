"""D1: AWS Bedrock Converse provider tests (D1).

D1 (REFACTOR_PLAN.md Lote D): native integration with AWS Bedrock via
the standardized Converse API.  ``boto3`` is imported lazily inside
:mod:`femtobot.providers.bedrock`, so the test suite doesn't pull
``boto3`` at collection time.

We test:

1. The registry exposes a ``bedrock`` :class:`ProviderSpec` (D1).
2. ``ProviderConfig`` accepts a ``region`` override (D1).
3. ``ProvidersConfig`` has a ``bedrock`` field (D1).
4. :func:`_resolve_region` honors the env-var chain in the documented
   order (``BEDROCK_REGION`` > ``AWS_REGION`` > ``AWS_DEFAULT_REGION``
   > ``us-east-1``).
5. :func:`_build_runtime_options` only sets the
   ``AWS_*`` shortcut env vars when no standard chain is set.
6. :class:`BedrockProvider` can be imported and constructed even
   without ``boto3`` installed (the constructor doesn't import it).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.providers


def test_bedrock_spec_registered() -> None:
    """D1: the provider registry lists ``bedrock`` (D1)."""
    from femtobot.providers.registry import find_by_name, list_provider_specs

    spec = find_by_name("bedrock")
    assert spec is not None
    assert spec.backend == "bedrock"
    assert spec.is_direct is True
    # All model-id keywords must be present so a single config can
    # match claude / nova / llama in one shot.
    assert "anthropic.claude" in spec.keywords
    assert "amazon.nova" in spec.keywords
    assert "meta.llama" in spec.keywords
    # And the registry exposes it via ``list_provider_specs``.
    names = {s.name for s in list_provider_specs()}
    assert "bedrock" in names


def test_provider_config_accepts_region() -> None:
    """D1: ``ProviderConfig.region`` is a public field (D1)."""
    from femtobot.config.schema import ProviderConfig

    cfg = ProviderConfig(api_key="x", region="sa-east-1")
    assert cfg.region == "sa-east-1"


def test_providers_config_has_bedrock_field() -> None:
    """D1: ``ProvidersConfig.bedrock`` is a public field (D1)."""
    from femtobot.config.schema import ProvidersConfig

    providers = ProvidersConfig()
    assert hasattr(providers, "bedrock")
    assert providers.bedrock.region is None
    assert providers.bedrock.api_key is None


def test_resolve_region_prefers_explicit() -> None:
    """D1: explicit region arg wins over env (D1)."""
    from femtobot.providers.bedrock import _resolve_region

    assert _resolve_region("sa-east-1") == "sa-east-1"


def test_resolve_region_uses_bedrock_region_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """D1: ``BEDROCK_REGION`` is the highest-priority env (D1)."""
    from femtobot.providers.bedrock import _resolve_region

    monkeypatch.setenv("BEDROCK_REGION", "sa-east-1")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    assert _resolve_region() == "sa-east-1"


def test_resolve_region_falls_back_to_aws_region(monkeypatch: pytest.MonkeyPatch) -> None:
    """D1: ``AWS_REGION`` is used when ``BEDROCK_REGION`` is unset (D1)."""
    from femtobot.providers.bedrock import _resolve_region

    monkeypatch.delenv("BEDROCK_REGION", raising=False)
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    assert _resolve_region() == "us-west-2"


def test_resolve_region_defaults_to_us_east_1(monkeypatch: pytest.MonkeyPatch) -> None:
    """D1: with no env vars, region is ``us-east-1`` (D1)."""
    from femtobot.providers.bedrock import _resolve_region

    monkeypatch.delenv("BEDROCK_REGION", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    assert _resolve_region() == "us-east-1"


def test_build_runtime_options_no_op_when_chain_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D1: standard AWS chain is left alone when present (D1)."""
    from femtobot.providers.bedrock import _build_runtime_options

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA-EXISTING")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret-existing")
    # Provide a session token too so the shortcut path is fully skipped.
    out = _build_runtime_options(api_key="my-token")
    # Standard chain stays put.
    assert "AWS_ACCESS_KEY_ID" not in out
    # And we don't override the existing access key.
    assert __import__("os").environ.get("AWS_ACCESS_KEY_ID") == "AKIA-EXISTING"


def test_build_runtime_options_uses_shortcut_when_chain_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D1: ``BEDROCK_API_KEY`` is mapped to ``AWS_SESSION_TOKEN`` (D1)."""
    from femtobot.providers import bedrock as mod

    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    out = mod._build_runtime_options(api_key="my-token")
    # The env was set.
    assert __import__("os").environ.get("AWS_SESSION_TOKEN") == "my-token"
    # And the function reports the same value.
    assert out == {"AWS_SESSION_TOKEN": "my-token"}


def test_bedrock_provider_constructs_without_boto3(monkeypatch: pytest.MonkeyPatch) -> None:
    """D1: the provider's __init__ does not import boto3 (D1)."""
    # Hide boto3 so a stray import would raise ImportError.
    import sys

    monkeypatch.setitem(sys.modules, "boto3", None)

    from femtobot.providers.bedrock import BedrockProvider

    provider = BedrockProvider(api_key="my-token", region="sa-east-1")
    # The provider remembers its region + default model without boto3.
    assert provider._region == "sa-east-1"
    assert provider.default_model.startswith("anthropic.claude")
    # The lazy client is None until first use.
    assert provider._client is None
