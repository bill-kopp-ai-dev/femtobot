# CLI Reference

Run `femtobot --help` for the canonical list. This page documents every
subcommand, its flags, and the in-REPL slash commands.

## Global flags

These work with every subcommand that targets an instance:

| Flag | Alias | Description |
|---|---|---|
| `--suffix <name>` | `-s` | Instance suffix (e.g. `dev`, `prod`, `billing`). See [multiple-instances.md](./multiple-instances.md). |
| `--folder-path <path>` | `-f` | Parent folder for the instance (overrides `$FEMTOBOT_HOME` and CWD). |
| `--workspace <path>` | `-w` | Override `agents.defaults.workspace` from `config.json`. |
| `--config <path>` | `-c` | Explicit path to `config.json` (otherwise auto-discovered). |

---

## `femtobot onboard`

Initialize a new instance. Creates the instance directory, writes a default
`config.json`, and syncs the workspace templates (`AGENTS.md`, `SOUL.md`,
`USER.md`, `MEMORY.md`).

```bash
femtobot onboard                              # ./.femtobot/
femtobot onboard --suffix dev                 # ./.femtobot_dev/
femtobot onboard --folder-path /opt/agents    # /opt/agents/.femtobot/
femtobot onboard --suffix billing --force     # overwrite existing config.json
```

| Option | Description |
|---|---|
| `--suffix`, `-s` | Instance suffix. |
| `--folder-path`, `-f` | Parent folder. |
| `--workspace`, `-w` | Workspace path. |
| `--config`, `-c` | Path to a seed `config.json`. |
| `--wizard` / `--no-wizard` | Interactive wizard on first run. |
| `--force` | Overwrite an existing `config.json`. |

---

## `femtobot status`

Show the resolved configuration for the current instance: config path,
workspace path, active model and provider, configured providers, and the
`mcpServers` currently registered.

```bash
femtobot status
femtobot status --suffix dev
```

Always run this after editing `config.json` — if Pydantic validation failed
at load time, `status` will show the silent fallback to defaults and you'll
know your overrides were dropped.

---

## `femtobot agent`

Run the agent loop. With no `-m`, drops you into an interactive REPL. With
`-m`, runs a single turn and exits.

```bash
femtobot agent                              # interactive REPL
femtobot agent -m "Hello!"                  # single-shot
femtobot agent --suffix dev -m "Hi dev!"    # against the dev instance
femtobot agent --session myproject          # isolated session id
femtobot agent --markdown                   # render output as Markdown (default)
femtobot agent --no-markdown                # plain text only
femtobot agent --logs                       # show tool calls and reasoning
femtobot agent --verbose                    # full femtobot.* logger output
```

| Option | Description |
|---|---|
| `--message`, `-m` | Run a single message and exit. |
| `--session`, `-s` | Session ID (default `cli:direct`). Different IDs keep independent histories. |
| `--workspace`, `-w` | Workspace override. |
| `--config`, `-c` | Path to `config.json`. |
| `--folder-path`, `-f` | Instance folder. |
| `--suffix` | Instance suffix. |
| `--markdown` / `--no-markdown` | Render assistant output as Markdown (default `true`). |
| `--logs` | Show tool calls and intermediate steps in the REPL. |

### In-REPL commands (slash commands)

Inside `femtobot agent` (interactive), the following slash commands are
registered by `femtobot.command.builtin`:

| Command | Description |
|---|---|
| `/help` | List available commands. |
| `/status` | Show current session / model / provider. |
| `/new` | Start a new session. |
| `/model` | Show the active model. |
| `/model <name>` | Switch model at runtime. |
| `/history` | Show recent session messages. |
| `/history <n>` | Show the last `n` messages. |
| `/goal` | Show the current long-running task description. |
| `/goal <text>` | Set / rewrite the long-running task. |
| `/dream` | Run the Dream consolidation job immediately (see [memory.md](./memory.md)). |
| `/dream-log` | Show the latest Dream diff. |
| `/dream-log <sha>` | Show a specific Dream diff. |
| `/dream-restore` | List recent Dream commits. |
| `/dream-restore <sha>` | Restore memory to the state before a given Dream commit. |
| `/stop` | Cancel the in-flight turn (priority). |
| `/restart` | Restart the agent loop (priority). |

Exit the REPL with `exit`, `quit`, `/exit`, `/quit`, `:q`, or `Ctrl+D`.

---

## `femtobot serve`

Start the OpenAI-compatible HTTP server (see [openai-api.md](./openai-api.md)).
By default binds to `127.0.0.1:8900` per the `api` block in `config.json`.

```bash
femtobot serve                              # default api.host:api.port
femtobot serve --port 9000                  # override
femtobot serve --host 0.0.0.0 --verbose     # bind all interfaces + show logs
femtobot serve --suffix dev --timeout 60    # 60s per-request timeout
```

| Option | Description |
|---|---|
| `--port`, `-p` | API server port (overrides `api.port`). |
| `--host`, `-H` | Bind address (overrides `api.host`). |
| `--timeout`, `-t` | Per-request timeout in seconds (overrides `api.timeout`). |
| `--verbose`, `-v` | Show Femtobot runtime logs (`loguru.enable("femtobot")`). |
| `--workspace`, `-w` | Workspace override. |
| `--config`, `-c` | Path to `config.json`. |

The server exposes `POST /v1/chat/completions`, `GET /v1/models`, and
`GET /health` on the same port. On startup it connects to every MCP server
in `tools.mcpServers` and tears them down on shutdown.

---

## `femtobot gateway`

Start the simplified headless gateway — currently exposes `GET /health` and
a stub `POST /v1/chat/completions` (returns `501 Not Implemented`). This is
the placeholder for the Stage-2 A2A / Docker orchestration work.

```bash
femtobot gateway
femtobot gateway --port 9001 --suffix prod
```

| Option | Description |
|---|---|
| `--port`, `-p` | Gateway port (default `8765`, or `gateway.port` from config). |
| `--workspace`, `-w` | Workspace override. |
| `--config`, `-c` | Path to `config.json`. |
| `--folder-path`, `-f` | Instance folder. |
| `--suffix`, `-s` | Instance suffix. |
| `--verbose`, `-v` | Verbose output. |

---

## Environment variables

| Variable | Effect |
|---|---|
| `FEMTOBOT_HOME` | Base path for instance directories (default: `~/.femtobot`). |
| `FEMTOBOT_<UPPER_SNAKE_CASE>` | Override any `config.json` value (see [configuration.md](./configuration.md#environment-variables)). |

---

## Roadmap Camada 1 — Quick Wins (input + slash discoverability)

Implementado em `agents.cli.*` no `config.json`. Todos os defaults são
backward-compatíveis: o comportamento atual é preservado quando o bloco
`cli` está ausente.

### Multiline

Termine a linha com `\` + `Enter` para inserir uma nova linha sem submeter.
Use `Ctrl+D` para submeter o bloco, `Ctrl+C` para cancelar. A flag é
`agents.cli.multiline` (`"off" | "backslash"`, default `"backslash"`).

### Slash completer

Digite `/` no REPL para ver os comandos disponíveis. O ranking é
**exato > prefixo > substring** (a lição do [GitHub issue #20537 do
Claude Code](https://github.com/anthropics/claude-code/issues/20537):
um match exato sempre vence um fuzzy). Flag: `agents.cli.completerEnabled`
e `agents.cli.completerMaxResults`.

### Bash mode

Digite `!` seguido do comando (ex: `!git log --oneline -5`). O output
fica visível no terminal mas não entra automaticamente no loop do agente
— assim você pode inspecionar sem queimar tokens. Flag:
`agents.cli.bashModeEnabled` e `agents.cli.bashModeTimeoutS` (default 30s).

### File mention

Digite `@` seguido do path (com `Tab` para completar). O token literal
`@path` é preservado no buffer. Flag: `agents.cli.fileMentionEnabled`.

### Whimsy (verbos caprichados)

Em vez de "thinking…", o spinner mostra "Percolating…", "Moonwalking…",
"Reticulating…". Flag: `agents.cli.whimsy.verbsEnabled` (default `true`).
Estilos de spinner suportados: `dots`, `dots2`, `dots3`, `line`,
`aesthetic`, `simpleDots` (`auto` = random).

### Themes

Quatro presets: `terracotta-claude` (default), `solarized-light`,
`cyber-dark`, `monochrome`. Mude em `agents.cli.theme` no `config.json`.
A flag aceita qualquer string; nomes inválidos caem no default.

### `/status` enriquecido

O comando `/status` agora renderiza um `rich.Panel` com 4 seções:
- **Context**: tokens usados / janela total + barra horizontal colorida.
- **Session**: modelo + tokens + elapsed.
- **Provider**: nome do modelo + `max_output_tokens`.
- **MCP**: servidores conectados / configurados + tools totais.

### Status line leve

Linha curta exibida no fim de cada turno com modelo, tokens e elapsed.
Flag: `agents.cli.sessionStatus.enabled`.

### Role header e turn spacing (Camada 4)

A Camada 4 introduziu melhorias para reduzir o ruído visual entre turnos.
Todos os knobs ficam sob `agents.defaults.cli.*` e têm defaults seguros
que podem ser sobrescritos em três caminhos (ver "Precedência" abaixo).

| Knob | Tipo | Range | Default | O que faz |
|---|---|---|---|---|
| `gap_after_turn` | int | 0..3 | `1` | Linhas em branco impressas **após** cada turno do agente. Resolve a UX-1 ("última mensagem colada na base do terminal"). `0` = sem gap, `3` = respiração generosa. |
| `role_header` | enum | `always` \| `minimal` \| `off` | `always` | Estilo do cabeçalho do agente impresso **antes** de cada turno. `always` (default) = barra colorida `🤖 Femtobot ▌`. `minimal` = só o emoji (legacy Camada 1). `off` = silencioso. |
| `user_separator` | bool | — | `true` | Quando `true`, imprime uma linha fina dim `· · · ·` logo após o usuário submeter input, emoldurando o reply do agente. `false` = conversa sem bordas. |

### Margins, breathing room e box delimiters (Camada 5)

A Camada 5 adiciona três knobs para resolver os 3 problemas de layout
restantes:

| Knob | Tipo | Range | Default | O que faz |
|---|---|---|---|---|
| `margin_x` | int | 0..8 | `4` | Caracteres de padding lateral (esquerda **e** direita) aplicados via `rich.Padding` ao redor de **todo** o output do agente. Resolve P1 ("texto colado nas extremidades"). `0` = sem padding (legacy). `8` ≈ metade de um terminal de 80 cols — máximo útil. **Aplica-se também ao box `[🤖 Femtobot]` / `[👤 You]` e ao separador `· · ·`** para que tudo fique alinhado visualmente (não só o corpo da resposta). |
| `gap_before_input` | int | 0..5 | `2` | Linhas em branco extras **antes** do `You:` prompt. Resolve P2 ("última mensagem colada na base"). `0` = prompt logo abaixo do reply. `5` = muito espaço, recomendado só para terminais altos. |
| `turn_box` | bool | — | `true` | Quando `true`, renderiza os cabeçalhos como boxes `[🤖 Femtobot]` (agente, cor terracotta) e `[👤 You]` (humano, cor azul). Cada turno vira um bloco visualmente delimitado — resolve P3 ("agente/humano indistinguíveis"). `false` = voltar à barra + `You:` legacy em ciano. |

Exemplo completo no `config.json`:

```json5
{
  "agents": {
    "defaults": {
      "cli": {
        // Camada 4 — turn spacing
        "gap_after_turn": 1,         // 0..3
        "role_header": "always",     // "always" | "minimal" | "off"
        "user_separator": true,
        // Camada 5 — visual separation
        "margin_x": 4,               // 0..8 (chars de padding lateral)
        "gap_before_input": 2,       // 0..5 (linhas antes do "You:")
        "turn_box": true             // [🤖 Femtobot] / [👤 You] boxes
      }
    }
  }
}
```

Defaults são backward-compatíveis: usuários existentes que não
configurarem esses campos veem o novo visual imediatamente.

### Tweak rápido via `/style` (REPL)

Os seis knobs acima podem ser ajustados **em tempo de execução** sem
reiniciar o femtobot, através do slash command `/style`:

```text
/style                                 # lista os valores atuais
/style set margin_x=6                  # aplica um knob
/style set margin_x=6 gap_after_turn=2 # aplica vários de uma vez
/style reset                           # reverte para os defaults do schema
```

Cada chamada valida os bounds (0..8 para `margin_x`, 0..3 para
`gap_after_turn`, 0..5 para `gap_before_input`, `always`/`minimal`/`off`
para `role_header`, bool para os demais). Valores fora da faixa são
rejeitados com mensagem de erro clara e o valor anterior é preservado.

Mudanças feitas com `/style` valem para a sessão atual (não persistem
em `config.json` nem em `.env`). Para persistir, edite `config.json`
ou exporte a env var correspondente.

### Override via env var / `.env`

O schema Pydantic herda de `BaseSettings` com prefixo `FEMTOBOT_` e
delimitador `__`, então qualquer knob pode ser sobrescrito sem editar
`config.json`:

```bash
# Padding lateral generoso + mais respiro entre turnos
export FEMTOBOT_AGENTS__DEFAULTS__CLI__MARGIN_X=6
export FEMTOBOT_AGENTS__DEFAULTS__CLI__GAP_AFTER_TURN=2
export FEMTOBOT_AGENTS__DEFAULTS__CLI__GAP_BEFORE_INPUT=3

# Desliga o visual "box" e usa apenas o cabeçalho emoji
export FEMTOBOT_AGENTS__DEFAULTS__CLI__TURN_BOX=false
export FEMTOBOT_AGENTS__DEFAULTS__CLI__ROLE_HEADER=minimal
```

Ou, equivalentemente, em um `.env` co-located com a instance directory:

```dotenv
FEMTOBOT_AGENTS__DEFAULTS__CLI__MARGIN_X=6
FEMTOBOT_AGENTS__DEFAULTS__CLI__GAP_AFTER_TURN=2
FEMTOBOT_AGENTS__DEFAULTS__CLI__TURN_BOX=true
```

**Precedência** (maior → menor):
1. `/style set …` (mutação em runtime, sessão-local)
2. env var / `.env`
3. `config.json`
4. Defaults do schema (`CLI_DEFAULT_*` em `config/schema.py`)

### Onde editar os defaults hard-coded

Se você quer mudar o **default de fábrica** (afetando instalações novas),
edite o bloco `CLI_DEFAULT_*` e `CLI_MIN/MAX_*` no topo de
[`femtobot/config/schema.py`](file:///home/bill/Codes/CLI-router-project/femtobot/femtobot/config/schema.py#L18-L122).
Esse é o único lugar que vale editar — `femtobot/cli/role_renderer.py`
re-exporta essas constantes como alias e há testes que validam a
identidade (`is`, não `==`) entre as duas.

### Migration: cli.* → agents.defaults.cli.*

O schema Pydantic do Camada 1 **não aceita** `cli.*` no nível raiz
(`extra="forbidden"`). Configs legadas com `cli.*` precisam ser migradas.

**Precedência**: `agents.defaults.cli.*` vence (caminho Pydantic mais específico).

Guia de migração:
1. Mova `cli.theme` → `agents.defaults.cli.theme`
2. Mova `cli.whimsy.*` → `agents.defaults.cli.whimsy.*`
3. Adicione os novos campos do Camada 1 (`bashModeEnabled`, `fileMentionEnabled`, etc.)

Valide sua config com:
```bash
uv run python3 scripts/check_cli_schema_compat.py
```

### Bloco de configuração (default)

```json5
{
  "agents": {
    "defaults": {
      "cli": {
        "multiline": "backslash",
        "completerEnabled": true,
        "completerMaxResults": 10,
        "bashModeEnabled": true,
        "bashModeTimeoutS": 30.0,
        "fileMentionEnabled": true,
        "theme": "terracotta-claude",
        "whimsy": {
          "verbsEnabled": true,
          "spinnerStyle": "auto",
          "verbPoolSize": 40
        },
        "sessionStatus": {
          "enabled": true,
          "showTokens": true,
          "showElapsed": true
        }
      }
    }
  }
}
```

---

## See also

- [configuration.md](./configuration.md) — full `config.json` reference
- [multiple-instances.md](./multiple-instances.md) — running `.femtobot` and
  `.femtobot_dev` side by side
- [memory.md](./memory.md) — what `/dream*` actually does
- [openai-api.md](./openai-api.md) — what `femtobot serve` exposes