# Changelog

All notable changes to Femtobot will be documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> Pre-1.0 (i.e., all current versions) treats breaking changes as minor bumps
> and minor changes as patches. The first 1.0 release will lock the API.

## [Unreleased]

## [0.0.7] — 2026-07-09

> Milestone `v0.0.7` — **Lote E: Hardening pós-release**. Revisão
> profunda do projeto (audit + ruff + smoke + race + security + 30
> testes de regressão). Apenas bugfixes e quality-of-life; **zero
> breaking changes**, **zero new features**. Compatível com v0.0.6.

> A seção `Tests` lista os arquivos de regressão; os bugs são
> referenciados como `E1..E7` nos comentários inline para
> localização rápida no `git blame`.

### Fixed
- **(E1, CRITICAL) `WebSocketChannel.gateway` não atribuído** —
  [femtobot/channels/websocket.py](femtobot/channels/websocket.py). O
  parâmetro ``gateway: GatewayServices = None`` era aceito no
  ``__init__`` mas nunca guardado em ``self.gateway``. O método
  ``_maybe_push_active_goal_state`` lia
  ``self.gateway.session_manager`` direto → ``AttributeError``
  garantido em 100% das chamadas quando o caller passava um gateway
  não-None. **Fix:** ``self.gateway = gateway`` no ``__init__``,
  mais guarda ``if self.gateway is None or self.gateway.session_manager is None``.
- **(E2, HIGH) Race em `_session_locks.setdefault`** —
  [femtobot/agent/loop.py](femtobot/agent/loop.py). Duas coroutines
  concorrentes podiam criar ``asyncio.Lock`` **diferentes** para o
  mesmo ``session_key`` via ``dict.setdefault`` (padrão TOCTOU),
  quebrando a serialização por sessão. **Fix:** novo método
  ``AgentLoop._acquire_session_lock()`` com double-check
  pattern + ``self._session_locks_lock`` (mesma técnica do
  ``Femtobot._acquire_session_lock`` já usado em B1).
- **(E3, HIGH) Kill-switch para `shell=True` em skill bodies** —
  [femtobot/cli/md_commands.py](femtobot/cli/md_commands.py). O
  ``_run_bash_inlines`` expandia ``!`rm -rf /``` (input do usuário
  ou skill body adulterada) com ``shell=True`` direto. **Fix:**
  nova env var ``FEMTOBOT_NO_BASH_INLINE=1`` como global kill-switch
  (substitui por placeholder sem chegar ao shell); toda expansão
  passa a gerar audit log com `cmd_length` + prefix do comando.
- **(E4, CRITICAL) `AgentLoop.from_config` retornava sem atribuir
  `instance`** — [femtobot/agent/loop.py](femtobot/agent/loop.py#L393)
  (F821). O snippet original fazia ``return cls(...)`` como
  expressão solta e depois ``instance._config = config`` —
  ``instance`` nunca era definido. O F821 mascarava isso como
  lint; o comando ``/style`` (que lê ``loop._config``) crashava
  em runtime. **Fix:** ``instance = cls(...)`` antes do assign.
- **(E5, HIGH) `atomic_write_text` com `from contextlib import
  suppress` no meio do try** —
  [femtobot/utils/gitstore.py](femtobot/utils/gitstore.py). O
  ``suppress`` era importado localmente dentro do try em
  ``atomic_write_text``, mas usado no bloco ``except`` logo abaixo.
  Resultado: ``UnboundLocalError`` em qualquer write que falhasse
  (deixava o ``.tmp`` órfão no disco). **Fix:** ``suppress``
  movido para o import do topo. Crítico porque todo `dream_cursor`
  / `history.jsonl` write passa por aqui.
- **(E6, MEDIUM) `RenderableType` undefined em `stream.py`** —
  [femtobot/cli/stream.py](femtobot/cli/stream.py#L164) (F821).
  Type annotation sem import. **Fix:** adicionado ao
  ``from rich.console import Console, RenderableType``.
- **(E7, MEDIUM) `Femtobot.run` `_extra_hooks` vazava em timeout**
  — [femtobot/femtobot.py](femtobot/femtobot.py). Quando
  ``lock.acquire()`` lançava ``TimeoutError``, o
  ``self._loop._extra_hooks`` (com o ``SDKCaptureHook``) **não**
  era restaurado e vazava para a próxima ``run()`` no mesmo
  Femtobot. **Fix:** try/finally aninhado garantindo o restore em
  happy path, timeout path e exception path.
- **(E8, MEDIUM) `AgentLoop._config` inexistente sem `from_config`**
  — [femtobot/agent/loop.py](femtobot/agent/loop.py). Quem
  instanciasse ``AgentLoop`` diretamente (sem ``from_config``)
  via ``__init__`` recebia ``self._config`` inexistente e
  slash commands crashavam. **Fix:**
  ``self._config: Any = None`` no ``__init__`` (default).
- **(E9, MEDIUM) `trust_env=False` quebrava HTTPS local com cert
  custom** — [femtobot/providers/openai_compat_provider.py](femtobot/providers/openai_compat_provider.py)
  (refinamento de D3). Aplicar ``trust_env=False`` a todo endpoint
  local desabilitava o ``SSL_CERT_FILE`` / ``SSL_CERT_DIR`` do
  env — quebrava setups ``https://127.0.0.1`` com self-signed
  CA. **Fix:** aplicar ``trust_env=False`` apenas quando o scheme
  é ``http://``; HTTPS local mantém ``trust_env=True`` para honrar
  a CA bundle custom.
- **(E10, LOW) `femtobot tools list` crashava em AttributeError**
  — [femtobot/cli/commands.py](femtobot/cli/commands.py). O
  ``except Exception`` mascarava um ``AttributeError`` em tools
  que falhavam no ``create(None)``. **Fix:** estreitado para
  ``(TypeError, ValueError, RuntimeError, AttributeError)``.
- **(E11, LOW) `keybindings._Handler` usava `handler_self` em vez
  de `self`** — [femtobot/cli/keybindings.py](femtobot/cli/keybindings.py)
  (N805). Nested class com rename incorreto; o método interno
  usava o nome ``handler_self``. **Fix:** renormalizado para
  ``self``.

### Added
- **(E) `ProviderConfig.region` (já em v0.0.6, refinado)** + novo
  helper ``_resolve_region`` em [femtobot/providers/bedrock.py](femtobot/providers/bedrock.py).

### Changed
- **(E) Ruff 100% limpo** — `uv run ruff check .` reporta
  `All checks passed!` (zero erros). 131 erros auto-fixados
  (imports não ordenados, blank lines com whitespace, trailing
  newlines, f-strings sem placeholders, etc.).
- **(E) `AgentLoop._acquire_session_lock` é async** — espelha
  o contrato de ``Femtobot._acquire_session_lock`` (B1).
- **(E) `E402` adicionado ao `pyproject.toml [tool.ruff.lint].ignore`**
  — re-exports de compat (ex.: ``DEFAULT_TURN_BOX``) ficam
  naturalmente abaixo das outras constantes sem warning.

### Tests
- Adicionados **30 testes de regressão** novos (não classificados
  sob os markers A/B/C/D — são puramente hardening):
  - `tests/test_websocket_channel_critical.py` (E1) — 5 testes
  - `tests/test_session_lock_race_fix.py` (E2) — 5 testes
  - `tests/test_md_commands_kill_switch.py` (E3) — 3 testes
  - `tests/test_femtobot_facade.py` (E1, E8, E11) — 8 testes
  - `tests/test_gitstore_atomic_write.py` (E5, E11) — 9 testes
- Suite total: **536 tests passing, 0 failed, 0 errors**.
- Ruff: **All checks passed**.

### Migration notes
Nenhuma. Compat 100% com v0.0.6 — todos os fixes são bugs
verdadeiros (variáveis undefined, race conditions, AttributeError
crash). Operadores que ativaram o kill-switch de E3 podem
desativar (default off).

## [0.0.6] — 2026-07-09

> Milestone `v0.0.6` — **Lote D: Provedores e cold-start** (see
> [REFACTOR_PLAN.md](./REFACTOR_PLAN.md) §5). 2 itens (D1, D3)
> implementados; D2 (extraQuery) já coberto pelo Lote A; D4 (gateway
> A2A) deferido até o Stage 2.

### Added
- (D1) **AWS Bedrock Converse provider** (ref: nanobot v0.2.0
  #3574).  Novo ``femtobot.providers.bedrock.BedrockProvider`` que
  usa a API padronizada Bedrock Converse.  ``boto3`` é importado
  **lazy** dentro de ``_get_client`` (não no topo do módulo), então
  uma instalação vanilla do femtobot não exige ``boto3``.  Suporta
  dois caminhos de auth:
  1. SigV4 padrão via ``AWS_ACCESS_KEY_ID`` /
     ``AWS_SECRET_ACCESS_KEY`` (e cadeia boto3 padrão — IAM role,
     SSO, etc.).
  2. Atalho de session token via ``BEDROCK_API_KEY``, mapeado
     automaticamente para ``AWS_SESSION_TOKEN`` quando a cadeia
     SigV4 não está presente.
- (D1) **`ProviderConfig.region` + `ProvidersConfig.bedrock`** (D1).
  Campo ``region`` no ``ProviderConfig`` permite sobrescrever
  ``BEDROCK_REGION`` / ``AWS_REGION`` / o default ``us-east-1``.
- (D1) **`pyproject.toml` extra `bedrock = ["boto3>=1.34.0"]`** —
  instala o SDK AWS sob demanda (`pip install femtobot[bedrock]`).

### Fixed
- (D3) **Local endpoints bypass corporate proxy** (ref: nanobot
  v0.2.2 #4367).  ``OpenAICompatProvider._build_client`` agora
  cria o ``httpx.AsyncClient`` com ``trust_env=False`` quando
  ``self._is_local`` é True.  ``HTTPS_PROXY`` / ``HTTP_PROXY`` no
  ambiente são ignorados para Ollama/vLLM/etc., resolvendo o
  cenário "Ollama atrás de corp proxy".  Cloud endpoints mantêm
  o default ``trust_env=True``.

### Tests
- Adicionados 14 testes de regressão marcados ``@pytest.mark.providers``:
  - `tests/test_bedrock_d1.py` (D1) — 10 testes
  - `tests/test_proxy_bypass_d3.py` (D3) — 4 testes

## [0.0.5] — 2026-07-09

> Milestone `v0.0.5` — **Lote C: Refator de arquitetura** (see
> [REFACTOR_PLAN.md](./REFACTOR_PLAN.md) §4). 5 itens propagados do
> nanobot v0.2.x. Foco em clareza de API para embedders (C1), plugin
> architecture (C2), extension registry (C3), capability mentions
> unificados (C4), e wizard de onboard (C5).

### Added
- (C2) **`Tool.capabilities` + `Tool.get_capabilities()`**
  (ref: nanobot v0.2.0 #3729).  Base class ``Tool`` agora expõe
  ``capabilities: list[str]`` (class-level) e o método
  ``get_capabilities()`` que adiciona ``read-only`` automaticamente
  quando ``read_only=True``.  ``ToolRegistry.by_capability(name)``
  filtra; ``ToolRegistry.capabilities()`` retorna um mapa
  capability→tools.
- (C2) **`femtobot tools list [--capability <name>]`** CLI
  (sub-app ``tools``).  Lista tools do registry; com
  ``--capability`` filtra; com ``--show-capabilities`` mostra
  tags ao lado do nome.
- (C3) **Local extension registry (`extensions.json`)** (ref:
  nanobot v0.2.1 #4046).  Novo módulo
  ``femtobot/agent/tools/extensions.py`` com
  :class:`ExtensionConfig` e :func:`load_extensions` que lê
  ``extensions.json`` do instance dir.  Suporta ``kind: cli`` e
  ``kind: http``; falha soft em JSON inválido.
- (C4) **`MCPServerConfig.capability_mentions`** (ref: nanobot
  v0.2.1 #3963).  Campo novo no schema.  Tags declaradas aqui
  fluem para ``MCPToolWrapper.get_capabilities()`` (junto com
  ``network``), expondo-as no system prompt.
- (C5) **`femtobot onboard --wizard`** (ref: nanobot v0.2.1
  #3890).  Wizard interativo (TTY-only) para escolher provider /
  model / API key.  Mutate o ``Config`` in-place e seta o novo
  preset como default.  TTY-only; CI/scripts seguem com o
  config default.

### Changed
- (C1) **`AgentLoop.from_config` documented as canonical entry
  point** (ref: nanobot v0.2.0 #3708).  Docstring expandida com
  exemplo de uso direto (sem facade) e link para ``Femtobot`` no
  :mod:`femtobot.femtobot`.  ``Femtobot.from_config`` já chama
  ``AgentLoop.from_config`` (verificado por teste).
- (C1) **`providers/registry.py::list_provider_specs()`** added
  (small additive change) so the wizard can iterate registered
  providers.

### Tests
- Adicionados 37 testes de regressão marcados ``@pytest.mark.architecture``:
  - `tests/test_agent_loop_factory_c1.py` (C1) — 4 testes
  - `tests/test_capabilities_c2.py` (C2) — 7 testes
  - `tests/test_extensions_c3.py` (C3) — 10 testes
  - `tests/test_capability_mentions_c4.py` (C4) — 7 testes
  - `tests/test_onboard_wizard_c5.py` (C5) — 9 testes

## [0.0.4] — 2026-07-09

> Milestone `v0.0.4` — **Lote B: Durabilidade e concorrência** (see
> [REFACTOR_PLAN.md](./REFACTOR_PLAN.md) §3). 6 itens propagados do
> nanobot v0.2.x. Foco em locks de sessão, usage real, continuação
> de goal, e integridade do apply_patch.

### Added
- (B1) **Per-session lock in `Femtobot.run()`** (ref: nanobot v0.2.1
  #4104).  ``Femtobot`` agora serializa chamadas concorrentes na
  mesma ``session_key`` via ``WeakValueDictionary[str, asyncio.Lock]``.
  Timeout de 5s para aquisição; ``asyncio.TimeoutError`` é levantado
  com mensagem clara.  ``lock_timeout_s=0`` desabilita o lock
  (escape hatch).  Compatível com a lock do servidor API que já
  existia.
- (B3) **Forward real LLM usage in `/v1/chat/completions`** (ref:
  nanobot v0.2.2 #4310).  ``Femtobot.run().usage`` carrega o dict
  de usage do provider; ``_chat_completion_response`` no
  ``api/server.py`` normaliza o dict (prompt/completion/total) e
  popula ``response.usage``.  Compat: quando o provider não
  retorna usage, o placeholder de zeros é mantido.
- (B6) **`/goal complete` slash command** (ref: nanobot v0.2.0
  #3788).  Novo handler ``cmd_goal_complete`` em
  ``command/builtin.py`` que muta ``session.metadata[GOAL_STATE_KEY]``
  para ``status="completed"`` + ``completed_at`` + ``recap``
  opcional.  O runner wall timeout volta ao default
  (``FEMTOBOT_LLM_TIMEOUT_S``).

### Fixed
- (B2) **Don't desiste while a goal is active** (ref: nanobot v0.2.1
  #3999, #4127).  Novo campo ``AgentRunSpec.goal_iteration_extra_budget``
  (default 50).  Quando ``max_iterations`` é esgotado e
  ``goal_active_predicate()`` retorna True, o loop ganha
  ``extra_budget`` iterações antes de finalizar.  Quando o extra
  budget também esgota, finaliza normalmente — sem loop infinito.

### Verified
- (B4) **`apply_patch` line-separated additions** (ref: nanobot
  v0.2.2 #4266).  Audit + 5 testes de regressão confirmam que
  ``action: "add"`` preserva o ``\n`` final e mantém múltiplas
  linhas distintas (sem collapse).
- (B5) **Archived summary lives in the system prompt** (ref: nanobot
  v0.2.0 #3711).  Audit + 3 testes confirmam que
  ``build_system_prompt(session_summary=...)`` injeta o summary
  como bloco ``[Archived Context Summary]`` no system prompt (não
  como mensagem), melhorando o cache hit em providers com KV cache.

### Tests
- Adicionados 27 testes de regressão marcados ``@pytest.mark.durability``:
  - `tests/test_session_lock_b1.py` (B1) — 5 testes
  - `tests/test_usage_b3.py` (B3) — 5 testes
  - `tests/test_apply_patch_b4.py` (B4) — 5 testes
  - `tests/test_context_b5_system_summary.py` (B5) — 3 testes
  - `tests/test_goal_complete_b6.py` (B6) — 5 testes
  - `tests/test_runner_b2_goal_budget.py` (B2) — 4 testes

## [0.0.3] — 2026-07-09

> Milestone `v0.0.3` — **Lote A: Estabilidade e segurança** (see
> [REFACTOR_PLAN.md](./REFACTOR_PLAN.md) §2). 14 itens propagados do
> nanobot v0.2.x.  Tudo gated por env var ou opt-in; backward-compat
> preservada com v0.0.2.

### Security
- (A2) **Reject unsafe MCP HTTP URLs before TCP probe**
  (ref: nanobot v0.2.2 #4123).  ``_preflight_check_mcp_url`` chama
  ``validate_url_target`` antes do ``_probe_http_url``.  ``http://169.254.169.254/``
  e afins são rejeitados no startup do MCP sem tentar conectar.
- (A3) **Validate redirect targets in web_fetch**
  (ref: nanobot v0.2.1 #3928).  Já estava implementado via
  ``_get_with_safe_redirects`` / ``_stream_with_safe_redirects``;
  audit confirmou cobertura de cada hop de redirect.
- (A4) **Block IPv6-mapped IPv4 addresses in SSRF guard**
  (ref: nanobot v0.2.1 #4086).  ``::ffff:0:0/96`` adicionado a
  ``_BLOCKED_NETWORKS`` como defense-in-depth sobre o
  ``_normalize_addr`` já existente.

### Fixed
- (A1) **Optional fail-fast on invalid config**
  (gated by ``FEMTOBOT_STRICT_CONFIG_LOAD``, default ``false``).  Em
  strict mode, ``JSONDecodeError`` / ``pydantic.ValidationError`` em
  campo obrigatório aborta com ``SystemExit(2)`` e mensagem clara.
  Em lenient mode (default), o loader continua caindo no default mas
  escala o log para ``error`` em JSON inválido / required-field
  inválido.  Novo subcomando CLI ``femtobot config validate [--strict]``.
- (A6) **dream_cursor advances only after commit succeeds**
  (ref: nanobot v0.2.0 #3631).  Novo
  ``MemoryStore.advance_dream_cursor_after_commit`` faz o
  ``git.auto_commit`` primeiro e só avança o cursor se a SHA voltar
  não-vazia; crash mid-Dream agora reprocessa os entries.
- (A7) **Atomic write for ``.dream_cursor`` + corruption detection**
  (ref: nanobot v0.2.0 #3606).  ``set_last_dream_cursor`` usa
  ``atomic_write_text`` (tempfile + ``os.replace`` + fsync do dir).
  Cursor corrompido na leitura é detectado e renomeado para
  ``*.corrupt-<ts>`` na próxima carga.
- (A8) **Soft workspace boundary with retry-throttle**
  (ref: nanobot v0.2.0 #3614).  Opt-in via
  ``FEMTOBOT_SOFT_WORKSPACE_BOUNDARY=true``.  Primeiros 3 strikes por
  sessão viram warning string retornada à LLM; após isso vira hard-fail
  novamente para não entrar em loop infinito.  Limite configurável via
  ``FEMTOBOT_SOFT_WORKSPACE_BOUNDARY_STRIKES``.
- (A9) **AutoCompact/Consolidator race fix**
  (ref: nanobot v0.2.1 #3881).  Já existia via
  ``Consolidator._locks`` (``WeakValueDictionary[session_key,
  asyncio.Lock]``); audit confirmou que ambos os caminhos pegam o
  mesmo lock por ``session_key``.
- (A10) **Ignore malformed history entries + monotonic cursor**
  (ref: nanobot v0.2.2 #4315, #4256).  Linhas JSONL malformadas
  geram warning one-shot com índice; cursor que regride é recusado com
  ``ValueError`` + log ``error``.

### Added
- (A5) **Log primary error before fallback** (ref: nanobot v0.2.0
  #4385).  ``FallbackProvider`` agora loga kind/code/status/content do
  erro primário antes de tentar fallback, e expõe
  ``on_primary_error`` callback para observability.
- (A11) **extraQuery config for OpenAI-compat providers**
  (ref: nanobot v0.2.2 #4217).  Novo campo ``extraQuery`` em
  ``ProviderConfig`` que vira query string da ``apiBase`` (azure-style
  ``?api-version=``, etc.).  Doc em
  [docs/configuration.md](./docs/configuration.md).
- (A12) **Sanitize Anthropic tool-use IDs**
  (ref: nanobot v0.2.2 #4356).  IDs que não casam
  ``^[a-zA-Z0-9_-]{1,64}$`` são sanitizados (substituição de
  caracteres inválidos + fallback hash determinístico).
- (A13) **Image placeholders no longer leak local path**
  (ref: nanobot v0.2.2 #4401).  ``image_placeholder_text`` retorna
  ``[image omitted]`` em vez de ``[image: /abs/path]``; o path não
  vaza mais em transcripts / logs / cloud upstream calls.
- (A14) **Recognize arrearage / 欠费 / payment_required as fallbackable**
  (ref: nanobot v0.2.1 #4048).  Tokens adicionados a
  ``_FALLBACK_ERROR_TOKENS`` no ``FallbackProvider``; o
  ``_ARREARAGE_ERROR_MESSAGE`` já existia no runner e continua
  exibindo mensagem amigável ao usuário.

### Tests
- Adicionados 51 testes de regressão marcados ``@pytest.mark.security``:
  - `tests/test_security_a4_ipv6_mapped.py` (A4)
  - `tests/test_mcp_a2_unsafe_url.py` (A2)
  - `tests/test_workspace_a8_soft_boundary.py` (A8)
  - `tests/test_config_loader_a1.py` (A1)
  - `tests/test_fallback_provider_a5_a14.py` (A5 + A14)
  - `tests/test_memory_a6_a7_a10.py` (A6 + A7 + A10)
  - `tests/test_providers_a11_a12.py` (A11 + A12)
  - `tests/test_helpers_a13.py` (A13)


- Documentation overhaul:
  - [docs/configuration.md](docs/configuration.md) now covers every field of
    `config.json` (60+ knobs across agents, channels, providers, api, gateway,
    tools, model presets).
  - [docs/python-sdk.md](docs/python-sdk.md) shows the in-process
    `Femtobot.from_config()` API alongside the OpenAI-server and CLI paths.
  - [docs/cli-reference.md](docs/cli-reference.md) documents every
    subcommand, every flag, and every slash command.
  - [docs/websocket.md](docs/websocket.md) covers the full schema and warns
    about the `websocketRequiresToken` default trap.
  - [docs/memory.md](docs/memory.md) explains the three-layer memory model,
    the Consolidator → AutoCompact → Dream pipeline, and every config knob.
  - [docs/openai-api.md](docs/openai-api.md) adds streaming, session
    semantics, and the no-auth caveat.
  - [docs/deployment.md](docs/deployment.md) gets a working systemd unit
    with a real `ExecStart` path, a supervisord alternative, a caddy/nginx
    reverse-proxy example, and health-check guidance.
  - [docs/my-tool.md](docs/my-tool.md) documents the `modify` action, the
    BLOCKED/READ_ONLY/`_SENSITIVE_NAMES`/`_DENIED_ATTRS` protection layers.
  - New docs: [architecture.md](docs/architecture.md),
    [tools.md](docs/tools.md), [security.md](docs/security.md),
    [troubleshooting.md](docs/troubleshooting.md), [mcp.md](docs/mcp.md).
  - Root-level [CHANGELOG.md](CHANGELOG.md) and
    [CONTRIBUTING.md](CONTRIBUTING.md).

### Fixed
- `docs/quick-start.md` install commands: `uv tool install femtobot-ai` →
  `uv tool install femtobot`; `git clone HKUDS/femtobot` →
  `git clone bill-kopp-ai-dev/femtobot`.
- `docs/websocket.md` example no longer ships a config that produces 401 on
  every connection (the `websocketRequiresToken: true` + empty token trap).
- `docs/deployment.md` systemd `ExecStart` no longer points at the
  non-existent `/path/to/femtobot` placeholder.
- `docs/python-sdk.md` no longer claims the Python API is "wait for stable
  release" — `Femtobot.from_config()` has been working since v0.0.2.

## [0.0.2] — 2025-11-XX

Initial public alpha.

### Added
- Core CLI commands: `onboard`, `status`, `agent`, `serve`, `gateway`.
- OpenAI-compatible HTTP surface under `femtobot serve`.
- WebSocket channel (`femtobot.channels.websocket`).
- 33 registered LLM providers.
- 13 native tools (filesystem, search, shell, web, self, message).
- MCP client integration with stdio and HTTP transports.
- Three-layer memory model: session messages → `history.jsonl` →
  Git-backed `MEMORY.md`/`USER.md`/`SOUL.md`, with the Consolidator, the
  AutoCompact idle compaction, and the periodic Dream job.
- Multiple-instance support via `--suffix` / `--folder-path` /
  `FEMTOBOT_HOME`.

[Unreleased]: https://github.com/bill-kopp-ai-dev/femtobot/compare/v0.0.7...HEAD
[0.0.7]: https://github.com/bill-kopp-ai-dev/femtobot/compare/v0.0.6...v0.0.7
[0.0.6]: https://github.com/bill-kopp-ai-dev/femtobot/compare/v0.0.5...v0.0.6
[0.0.5]: https://github.com/bill-kopp-ai-dev/femtobot/compare/v0.0.4...v0.0.5
[0.0.4]: https://github.com/bill-kopp-ai-dev/femtobot/compare/v0.0.3...v0.0.4
[0.0.3]: https://github.com/bill-kopp-ai-dev/femtobot/compare/v0.0.2...v0.0.3
[0.0.2]: https://github.com/bill-kopp-ai-dev/femtobot/releases/tag/v0.0.2