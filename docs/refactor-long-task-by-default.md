# Plano de Refatoração V2 — Long Task como modo padrão no femtobot

> **Status:** rascunho revisado para execução futura.
> **Escopo:** completar a feature de sustained goal no `femtobot` e torná-la
> o modo de execução padrão quando `agents.defaults.longTask.byDefault=true`.
> **Objetivo adicional desta V2:** corrigir lacunas do plano anterior nos
> caminhos `API`/`SDK`, no timeout externo HTTP, na disponibilidade de
> `complete_goal` ao longo do ciclo de vida do goal e no protocolo de
> `ask_orchestrator`.
> **Compat:** preservar 100% do comportamento atual quando `byDefault=false`.

---

## 0. Resumo executivo

O plano V1 acertava a direção geral, mas tinha quatro riscos estruturais:

1. tratava corretamente o loop por bus, mas **não tratava `API`/`SDK` como
   caminhos de primeira classe**;
2. removia o timeout interno do runner, mas **não removia o timeout externo do
   servidor HTTP**, que continuaria matando as long tasks;
3. propunha habilitar `long_task`/`complete_goal` via `enabled(ctx)` com base
   em `goal_requested`, mas isso **não reflete o fato de que goal ativo é estado
   persistente da sessão**, não do turno;
4. propunha `ask_orchestrator` blocking, mas **sem protocolo explícito de
   correlação, persistência, retomada e timeout**.

Esta V2 reorganiza a refatoração para começar pelo **modelo operacional do
worker**, não pelas tools isoladamente.

---

## 1. Princípios desta V2

| # | Princípio | Decisão |
|---|---|---|
| P1 | `API` e `SDK` são canais primários do worker | A long task precisa funcionar neles desde a Fase 1 |
| P2 | Goal é estado de sessão, não estado de turno | `complete_goal` deve estar disponível sempre que houver goal ativo |
| P3 | Pergunta blocking precisa de protocolo | `ask_orchestrator` terá `correlation_id`, persistência e retomada formal |
| P4 | HTTP síncrono não é bom contrato para trabalho longo | Introduzir modo assíncrono de job/session quando long task estiver ativa |
| P5 | Compatibilidade é mandatória | `byDefault=false` mantém o comportamento atual byte-a-byte |

---

## 2. Decisões de design confirmadas

| # | Decisão | Escolha |
|---|---|---|
| D1 | Tratamento de mensagens triviais com `byDefault=true` | **Tudo vira goal automaticamente** |
| D2 | Mecanismo de dúvida crítica | **`ask_orchestrator` + fallback para `message`** |
| D3 | Local do flag no config | **`agents.defaults.longTask.{...}`** |

---

## 3. Mudança principal de arquitetura

O `femtobot` passará a ter **dois modos de entrega** quando uma long task
estiver ativa:

| Canal | Comportamento atual | Comportamento alvo |
|---|---|---|
| Bus / loop interno | Continuações invisíveis por `pending_queue` | Mantido e expandido |
| `process_direct()` / SDK | Execução síncrona sem `pending_queue` | Passa a suportar fila efêmera local ou modo assíncrono controlado |
| API HTTP OpenAI-compat | Request síncrona limitada por `api.timeout` | Passa a oferecer `asyncGoalMode` com sessão/job durável |

### Diretriz

O plano deixa de assumir que “desligar timeout no runner” basta. O design
correto é:

- o runner controla o **timeout interno do LLM**;
- o loop controla a **continuação do goal**;
- a API controla o **contrato externo** com o orquestrador;
- o goal é **persistido na sessão** e não depende de um único request HTTP.

---

## 4. Estratégia operacional por canal

### 4.1 Bus / loop interno

Mantém o modelo atual baseado em `pending_queue`, mas com goal management
completo.

### 4.2 `process_direct()` e SDK

`process_direct()` passa a ter duas opções explícitas:

- `execution_mode="sync"`: comportamento atual, indicado para respostas
  curtas e debugging;
- `execution_mode="goal_aware"`: cria uma fila efêmera local para permitir
  continuações invisíveis, `ask_orchestrator` blocking e retomadas do goal
  dentro do mesmo `session_key`.

Quando `longTask.byDefault=true`, o `SDK` usará `goal_aware` por default.

### 4.3 API OpenAI-compat

O servidor HTTP passa a suportar dois contratos:

- `sync`:
  resposta síncrona tradicional, preservada para compatibilidade;
- `async_goal`:
  request aceita a mensagem, associa ao `session_id`, devolve imediatamente
  `202 Accepted` com `goal_id`/`session_id`, e o progresso passa a ser
  consultado via:
  - polling;
  - SSE;
  - ou leitura posterior da sessão.

**Conclusão operacional:** long task real em arquitetura supervisor-worker
deve usar `async_goal` na API, não `sync`.

---

## 5. Arquivos a criar

### 5.1 `femtobot/agent/tools/long_task.py`

Implementa as tools reais:

- `LongTaskTool`
- `CompleteGoalTool`

Diferença importante da V2:

- `LongTaskTool` é visível quando:
  - `byDefault=true`; ou
  - o turno veio de `/goal`; ou
  - o chamador interno do loop for o bootstrap automático do goal;
- `CompleteGoalTool` é visível **sempre que existir goal ativo na sessão**,
  mesmo que o turno atual não tenha `goal_requested`.

Isso elimina o erro conceitual do gating baseado apenas no turno inicial.

### 5.2 `femtobot/agent/tools/ask_orchestrator.py`

Nova tool com protocolo completo.

Schema base:

```json
{
  "question": {"type": "string", "minLength": 1, "maxLength": 4000},
  "context": {"type": ["string", "null"], "maxLength": 8000},
  "options": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
  "timeoutS": {"type": "number", "minimum": 30, "maximum": 86400, "default": 1800},
  "blocking": {"type": "boolean", "default": true},
  "target": {"type": ["string", "null"], "enum": ["orchestrator", "human", null]}
}
```

### 5.3 `femtobot/agent/goal_permission.py`

Portado do `nanobot`, com uma nuance:

- o gate protege a **criação** e a **substituição** do goal;
- a **finalização** (`complete`, `cancel`, `block`) deve ser permitida sempre
  que houver goal ativo e a tool esteja visível.

### 5.4 `femtobot/runtime_context.py`

Mesmo propósito do plano V1, mas agora com suporte explícito a:

- bloco de goal ativo;
- bloco de pergunta pendente ao orquestrador;
- bloco de “goal blocked waiting response”.

### 5.5 `femtobot/session/pending_asks.py`

Novo módulo para persistir e resolver perguntas bloqueantes.

Responsabilidades:

- armazenar asks pendentes por `session_key`;
- gerar `correlation_id`;
- registrar `created_at`, `deadline_at`, `status`;
- vincular resposta recebida à pergunta correta;
- sobreviver a restart do processo.

### 5.6 `femtobot/api/goal_runtime.py`

Novo módulo de apoio ao servidor HTTP para:

- criar `goal_id`;
- devolver `202 Accepted`;
- publicar progresso;
- consultar status;
- recuperar resposta final.

---

## 6. Arquivos a modificar

### 6.1 `femtobot/config/schema.py`

Adicionar:

```python
class LongTaskApiMode(str, Enum):
    SYNC = "sync"
    ASYNC_GOAL = "async_goal"
    AUTO = "auto"


class LongTaskConfig(Base):
    by_default: bool = False
    max_goal_rounds: int = Field(default=12, ge=1)
    max_goal_runtime_s: float = Field(default=14400.0, ge=60.0)
    max_goal_wall_idle_s: float = Field(default=1800.0, ge=60.0)
    max_goal_ask_attempts: int = Field(default=3, ge=1)
    goal_iteration_extra_budget: int = Field(default=50, ge=0)
    escalation_channel: str | None = None
    escalation_chat_id: str | None = None
    progress_report_every_n_turns: int = Field(default=0, ge=0)
    progress_report_to: str = "self"
    require_objective_self_containment: bool = True
    block_on_workspace_violation: bool = True
    workspace_violation_threshold: int = Field(default=3, ge=1)
    sdk_execution_mode: Literal["sync", "goal_aware"] = "goal_aware"
    api_mode: LongTaskApiMode = LongTaskApiMode.AUTO
    api_async_accept_timeout_s: float = Field(default=5.0, ge=0.5)
```

### 6.2 `femtobot/agent/loop.py`

#### Ajuste 1: `process_direct()` vira caminho de primeira classe

Adicionar parâmetros:

```python
async def process_direct(
    ...,
    execution_mode: Literal["sync", "goal_aware"] = "sync",
    allow_internal_continuation: bool | None = None,
)
```

Regras:

- `sync` mantém o comportamento atual;
- `goal_aware` cria uma `pending_queue` efêmera local para o `session_key`;
- `allow_internal_continuation` default:
  - `False` em `sync`
  - `True` em `goal_aware`

#### Ajuste 2: `_state_command`

Antes do dispatch:

- se `byDefault=true` e a inbound não é slash command, marcar:
  - `goal_requested=True`
  - `goal_requested_implicitly=True`
  - `goal_started_at`

**Importante:** não é mais obrigatório sobrescrever `original_command="/goal"`.
Em vez disso, o runtime passa a usar `explicit_goal_requested()` e
`implicit_goal_requested()` como conceitos distintos.

#### Ajuste 3: `_auto_wrap_inbound_as_goal`

Ainda existe, mas com regra refinada:

- só cria goal implícito quando:
  - `byDefault=true`;
  - não existe goal ativo;
  - o turno não é continuação interna;
  - o turno não é resposta a `ask_orchestrator`.

#### Ajuste 4: publicação de eventos

`loop.py` passa a publicar `GoalStateChanged` e `AskStateChanged`
estruturadamente.

### 6.3 `femtobot/agent/runner.py`

Adicionar ao `AgentRunSpec`:

- `goal_runtime_cap_s`
- `goal_idle_cap_s`
- `goal_visible_tools_predicate`
- `ask_pending_predicate`

#### Regra V2 importante

O runner **não** deve depender de `byDefault` para decidir se um goal está
ativo. A fonte da verdade é:

- `sustained_goal_active(session.metadata)`; ou
- turno atual explicitamente marcando bootstrap de goal.

#### Timeout

O runner continua responsável apenas pelo timeout **interno** do LLM.
O timeout **externo** do canal é tratado fora dele.

### 6.4 `femtobot/api/server.py`

Este é o principal ajuste da V2.

#### Problema atual

Hoje o servidor envolve `process_direct(...)` em `asyncio.wait_for(...)`,
o que mata long tasks mesmo quando o runner desligou `FEMTOBOT_LLM_TIMEOUT_S`.

#### Solução V2

Adicionar três caminhos:

1. `sync`
   - comportamento atual;
2. `async_goal`
   - se o request criar ou detectar long task, retorna:
     ```json
     {
       "status": "accepted",
       "session_id": "...",
       "goal_id": "...",
       "poll_url": "...",
       "events_url": "..."
     }
     ```
3. `auto`
   - usa `sync` para requests triviais e `async_goal` para turns com goal.

Também adicionar endpoints auxiliares:

- `GET /v1/goals/{goal_id}`
- `GET /v1/goals/{goal_id}/events`
- `POST /v1/goals/{goal_id}/answer`

### 6.5 `femtobot/femtobot.py`

`Femtobot.run()` passa a aceitar:

```python
async def run(
    message: str,
    *,
    session_key: str = "sdk:default",
    execution_mode: Literal["sync", "goal_aware"] | None = None,
    hooks: list[AgentHook] | None = None,
)
```

Default:

- lê de `config.agents.defaults.longTask.sdkExecutionMode`;
- quando `byDefault=true`, `goal_aware` é o default recomendado.

### 6.6 `femtobot/agent/tools/loader.py`

**Correção importante da V2:**

Não usar `enabled(ctx)` para decidir visibilidade por turno do `complete_goal`.

`enabled(ctx)` fica restrito a condições estáticas:

- config habilitada;
- dependências disponíveis;
- contexto de sessão existe.

A decisão “esta tool aparece neste turno?” passa para o loop/context builder,
que monta a lista final de tool schemas por turno.

### 6.7 `femtobot/agent/context.py`

Adicionar capacidade de filtrar tool schemas por turno:

```python
build_tool_schemas(
    registry,
    *,
    session_metadata,
    message_metadata,
    long_task_config,
)
```

Regras:

- `long_task` aparece quando o goal pode ser criado neste turno;
- `complete_goal` aparece quando há goal ativo;
- `ask_orchestrator` aparece sempre;
- `replace` é permitido apenas quando a permissão de mutação estiver ativa.

### 6.8 `femtobot/command/builtin.py`

Atualizar:

- `/goal <objective>`: passa a criar goal explicitamente, sem depender do LLM;
- `/goal complete [recap]`
- `/goal cancel [reason]`
- `/goal block [reason]`
- `/goal status`

Esses comandos passam a usar o mesmo núcleo de domínio das tools para evitar
duplicação de regra.

### 6.9 `femtobot/session/goal_state.py`

Adicionar:

- `MAX_GOAL_OBJECTIVE_CHARS = 4000`
- `GOAL_ACTIONS = ("complete", "cancel", "block", "replace")`
- `explicit_goal_requested(...)`
- `implicit_goal_requested(...)`
- `goal_bootstrap_requested(...)`
- helpers para goal runtime:
  - `goal_started_at(...)`
  - `goal_elapsed_s(...)`
  - `goal_block_reason(...)`

### 6.10 `femtobot/session/turn_continuation.py`

Generalizar o mecanismo de continuação para suportar:

- continuação por budget;
- continuação aguardando resposta do orquestrador;
- continuação após restart.

Adicionar `continuation_kind`:

- `sustained_goal`
- `ask_wait`
- `goal_resume`

### 6.11 `femtobot/bus/runtime_events.py`

Além de `GoalStateChanged`, adicionar:

```python
@dataclass(frozen=True)
class AskStateChanged:
    context: RuntimeEventContext
    correlation_id: str
    status: str
    session_metadata: dict[str, Any] = field(default_factory=dict)
```

### 6.12 `femtobot/templates/agent/goal_runtime.md`

Atualizar o guidance:

- goals são a forma padrão de trabalho do worker quando `byDefault=true`;
- use `complete_goal` ao terminar;
- use `ask_orchestrator` apenas para dúvidas realmente bloqueantes;
- não ficar preso em loop de asks.

---

## 7. Protocolo de `ask_orchestrator`

Esta é a maior adição da V2.

### 7.1 Estrutura persistida

Cada ask pendente fica salvo em metadata de sessão:

```json
{
  "pending_asks": [
    {
      "correlation_id": "ask_...",
      "target": "orchestrator",
      "question": "...",
      "context": "...",
      "options": ["A", "B"],
      "status": "pending",
      "created_at": "...",
      "deadline_at": "...",
      "response": null
    }
  ]
}
```

### 7.2 Envio

A tool:

1. gera `correlation_id`;
2. persiste o ask antes de enviar a mensagem;
3. envia `OutboundMessage` com:
   - `metadata["ask_correlation_id"]`
   - `metadata["session_key"]`
   - `metadata["goal_id"]`
4. se `blocking=true`, marca o goal como `waiting_on="ask_orchestrator"`.

### 7.3 Resposta

A resposta do supervisor/humano deve trazer o `correlation_id`.

Caminhos aceitos:

- `POST /v1/goals/{goal_id}/answer`
- slash/internal command
- inbound com `metadata["ask_correlation_id"]`

### 7.4 Retomada

Ao receber a resposta:

1. resolver o ask persistido;
2. gravar a resposta em metadata;
3. enfileirar `goal_resume` na fila da sessão;
4. reabrir o runner com o contexto “Pergunta respondida”.

### 7.5 Timeout

Se `deadline_at` expirar:

- marcar ask como `timed_out`;
- publicar `AskStateChanged`;
- injetar continuação dizendo:
  - “nenhuma resposta chegou”;
  - “use a melhor hipótese ou bloqueie o goal”.

---

## 8. Disponibilidade das tools por turno

Esta seção substitui o gating incorreto da V1.

### Regra correta

A disponibilidade da tool no prompt é calculada **por turno**, não no loader.

| Tool | Regra de visibilidade |
|---|---|
| `long_task` | visível quando criação/substituição é permitida |
| `complete_goal` | visível sempre que houver goal ativo |
| `ask_orchestrator` | sempre visível |
| `replace` | action permitida apenas se a permissão de mutação estiver ativa |

### Consequência

O `ToolLoader.enabled(ctx)` deixa de carregar responsabilidade de política
por turno. Ele continua apenas decidindo se a tool existe no processo.

---

## 9. Fluxo end-to-end com `byDefault=true`

```text
Inbound -> Loop detecta byDefault -> bootstrap implícito do goal
       -> goal_state ativo persistido
       -> tool schemas do turno incluem complete_goal
       -> runner trabalha sem timeout interno de LLM
       -> se budget estoura:
            - bus path: pending_queue normal
            - sdk/api goal_aware: fila efêmera ou job assíncrono
       -> se dúvida crítica:
            - ask_orchestrator gera correlation_id
            - persiste pending_ask
            - aguarda resposta
            - resposta retoma goal pelo mesmo session_key
       -> complete_goal(action="complete"|"block"|"cancel")
       -> goal finalizado
```

---

## 10. Guardrails revisados

| Risco | Mitigação |
|---|---|
| Loop infinito no runner | `goal_iteration_extra_budget` + `max_goal_rounds` |
| Goal eterno por múltiplas continuações | `max_goal_runtime_s` |
| Idle longo | `max_goal_wall_idle_s` |
| Perguntas demais ao supervisor | `max_goal_ask_attempts` |
| HTTP síncrono matar goal | `apiMode=async_goal` ou `auto` |
| `complete_goal` sumir do prompt | visibilidade por turno baseada em `goal ativo` |
| Retomada ambígua do ask | `correlation_id` persistido |
| Restart durante ask pendente | `pending_asks` persistido em sessão |
| Goal sem critério de done | `require_objective_self_containment=true` |
| Violação repetida de workspace | `workspace_violation_threshold` + `block_on_workspace_violation` |

---

## 11. Fases de implementação revisadas

### Fase 0 — Preparação do contrato operacional

1. Adicionar `LongTaskConfig` ao schema
2. Introduzir `apiMode`, `sdkExecutionMode`
3. Adicionar módulos `pending_asks.py` e `goal_runtime.py`
4. Escrever testes de contrato para `API`, `SDK` e `process_direct`

### Fase 1 — Núcleo de domínio do goal

1. Criar `goal_permission.py`
2. Criar `long_task.py`
3. Unificar lógica dos slash commands com as tools
4. Publicar `GoalStateChanged`
5. Adicionar helpers em `goal_state.py`

### Fase 2 — Visibilidade por turno e runtime context

1. Adicionar `runtime_context.py`
2. Filtrar tool schemas por turno em `context.py`
3. Garantir visibilidade de `complete_goal` em goal ativo
4. Atualizar template `goal_runtime.md`

### Fase 3 — Continuação multi-canal

1. Tornar `process_direct(..., execution_mode="goal_aware")` funcional
2. Generalizar `turn_continuation.py`
3. Propagar `pending_queue` ou equivalente para `SDK`
4. Testes de continuação em `bus`, `sdk` e `process_direct`

### Fase 4 — API assíncrona de worker

1. Implementar `async_goal` em `api/server.py`
2. Adicionar endpoints de status/eventos/resposta
3. Garantir compatibilidade do modo `sync`
4. Testes E2E com supervisor chamando worker por HTTP

### Fase 5 — `ask_orchestrator`

1. Implementar tool
2. Implementar persistência e resolução de asks
3. Implementar retomada por `correlation_id`
4. Testes de timeout, restart e replay

### Fase 6 — UX e polish

1. `/goal cancel`
2. `/goal block`
3. `/goal status`
4. `sessions list` com active goal
5. documentação final

---

## 12. Critérios de aceitação revisados

- [ ] `byDefault=false` preserva o comportamento atual byte-a-byte
- [ ] `byDefault=true` funciona em:
  - bus
  - `process_direct`
  - SDK
  - API
- [ ] `complete_goal` permanece visível em todo turno com goal ativo
- [ ] `ask_orchestrator` funciona com `correlation_id` persistido
- [ ] restart do processo não perde asks pendentes nem o estado do goal
- [ ] API `sync` segue compatível
- [ ] API `async_goal` suporta polling ou SSE
- [ ] nenhum timeout externo HTTP mata long task no modo assíncrono
- [ ] nenhum caminho permite loop infinito sem guardrail

---

## 13. Riscos e mitigação

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| Complexidade adicional na API | Alta | Alto | Isolar `goal_runtime.py` e manter `sync` intacto |
| Regressão no SDK | Média | Alto | `execution_mode` explícito + testes dedicados |
| Correlação incorreta de asks | Média | Alto | `correlation_id` persistido e endpoint dedicado de resposta |
| Duplicação de lógica entre slash command e tool | Média | Médio | extrair serviço de domínio único |
| Goals triviais custarem mais | Alta | Baixo | aceito por decisão de produto D1 |

---

## 14. Próximos passos recomendados

1. aprovar esta V2 como baseline;
2. iniciar pela **Fase 0**, não pela tool;
3. só depois entrar na implementação de `long_task`/`complete_goal`;
4. deixar `ask_orchestrator` para depois de o caminho `API/SDK` já estar
   correto.

---

> **Sequência recomendada de execução real:** `schema/config` →
> `goal domain` → `tool visibility per turn` → `process_direct/sdk` →
> `api async_goal` → `ask_orchestrator`.
