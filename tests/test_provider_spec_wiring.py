"""``OpenAICompatProvider`` spec wiring tests (v0.1.0 fifth-pass I1, I2).

Audit I1: ``OpenAICompatProvider.__init__`` annotated ``spec: None
= None`` and the factory passed ``spec=None``.  The result was
that every provider-specific branch in
``OpenAICompatProvider`` (prompt caching, model prefix
stripping, thinking style, tool-ID sanitization, env vars)
was silently disabled.

Audit I2: ``_setup_env`` was defined but never called, so
``spec.env_key`` / ``spec.env_extras`` were dead code.

We pin:

* the factory resolves the spec via ``find_by_name(provider_name)``
  and passes it to the provider,
* the provider stores the spec in ``self._spec``,
* the spec is forwarded to the OpenAI-compat provider so
  provider-specific features (e.g. prompt caching for
  Anthropic via Bedrock) actually activate.
"""

from __future__ import annotations

from types import SimpleNamespace

from femtobot.providers.factory import _make_provider_core
from femtobot.providers.openai_compat_provider import OpenAICompatProvider
from femtobot.providers.registry import find_by_name


def test_factory_passes_provider_spec_to_openai_compat(tmp_path) -> None:
    """I1: factory passes ``spec`` to ``OpenAICompatProvider`` (I1).

    We use a real provider name from the registry (e.g. ``ollama``)
    so the factory's ``find_by_name`` lookup succeeds without a
    mock.  The test confirms the spec flows through to
    ``provider._spec`` instead of being ``None``.
    """
    cfg = SimpleNamespace(
        workspace_path=tmp_path,
        agents=SimpleNamespace(defaults=SimpleNamespace(fallback_models=[])),
        model_presets={},
    )
    cfg.resolve_preset = lambda preset_name=None: SimpleNamespace(
        model="llama3.1",
        max_tokens=4096,
        temperature=0.0,
        context_window_tokens=8192,
        reasoning_effort=None,
        to_generation_settings=lambda: SimpleNamespace(
            max_tokens=4096, temperature=0.0, reasoning_effort=None
        ),
    )
    cfg.get_provider_name = lambda m, preset=None: "ollama"
    cfg.get_api_base = lambda m, preset=None: "http://localhost:11434/v1"
    cfg.get_provider = lambda m, preset=None: SimpleNamespace(
        api_key="",
        api_type="auto",
        extra_headers=None,
        extra_body=None,
        extra_query=None,
    )

    provider = _make_provider_core(cfg)

    assert isinstance(provider, OpenAICompatProvider)
    # The factory must have resolved the spec and forwarded it.
    assert provider._spec is not None
    assert provider._spec.name == "ollama"


def test_setup_env_is_called_with_api_key() -> None:
    """I2: ``_setup_env`` is called from ``__init__`` (I2)."""
    captured: list[dict] = []

    class _StubProvider(OpenAICompatProvider):
        def _setup_env(self, api_key, api_base):  # type: ignore[override]
            captured.append({"api_key": api_key, "api_base": api_base})

    spec = find_by_name("zhipu")
    assert spec is not None
    p = _StubProvider(api_key="my-key", api_base="https://api.z.ai/v1", spec=spec)
    assert len(captured) == 1
    assert captured[0]["api_key"] == "my-key"


def test_setup_env_not_called_when_api_key_is_none() -> None:
    """I2: ``_setup_env`` is skipped when no API key is provided (I2)."""
    captured: list[dict] = []

    class _StubProvider(OpenAICompatProvider):
        def _setup_env(self, api_key, api_base):  # type: ignore[override]
            captured.append({"api_key": api_key, "api_base": api_base})

    spec = find_by_name("zhipu")
    assert spec is not None
    _StubProvider(api_key=None, api_base="https://api.z.ai/v1", spec=spec)
    assert captured == []


def test_spec_typed_as_provider_spec() -> None:
    """I1: the constructor accepts ``ProviderSpec | None`` (I1)."""
    import inspect

    sig = inspect.signature(OpenAICompatProvider.__init__)
    spec_param = sig.parameters.get("spec")
    assert spec_param is not None
    annotation = str(spec_param.annotation)
    # The annotation should no longer be the deliberately
    # restrictive ``None``.
    assert "None" not in annotation or "ProviderSpec" in annotation
    assert "ProviderSpec" in annotation
