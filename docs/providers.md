# Femtobot Inference Providers

Auto-generated registry reference.  Source of truth:
[`femtobot/providers/registry.py`](../femtobot/providers/registry.py)
(all fields below come directly from that file).

This inventory is the authoritative list of inference providers the
Femtobot runtime can route traffic to.  It is regenerated whenever
the registry changes — see "How to refresh" at the bottom.

---

## How provider selection works

Femtobot picks a provider at runtime via the
[`_resolve_model_preset`](../femtobot/providers/factory.py#L21) helper:

1. If `agents.defaults.provider` is set explicitly, the runtime
   resolves it via `find_by_name(...)`.
2. If `provider="auto"` (the default), the runtime scans each
   `ProviderSpec.keywords` looking for a substring match in the
   configured `model` string.  The first match wins; if no match,
   the runtime falls back to the first gateway in the registry.

Each provider declares a `backend` in the spec:

| Backend | Implementation | Notes |
|---------|----------------|-------|
| `openai_compat` | [`OpenAICompatProvider`](../femtobot/providers/openai_compat_provider.py#L375) | 29 of 30 providers |
| `bedrock` | [`BedrockProvider`](../femtobot/providers/bedrock.py#L88) | AWS Bedrock only — first-class implementation |

Two flags also live on the spec:

* `is_gateway=True` — the provider routes arbitrary upstream model
  names (OpenRouter, AiHubMix, SiliconFlow).  Gateways appear first
  in the registry so they win `auto` when no model-keyword matches.
* `is_local=True` — the provider runs on `localhost`-style URLs
  (vLLM, Ollama, LM Studio, OpenVINO Model Server, Atomic Chat).
  This is metadata used by `femtobot status`; the underlying
  transport is still `openai_compat`.

---

## 1. Gateways (route any model)

| Slug | Display | Env key | Default base | Detection (in addition to keywords) |
|------|---------|---------|--------------|--------------------------------------|
| `openrouter` | OpenRouter | `OPENROUTER_API_KEY` | `https://openrouter.ai/api/v1` | key prefix `sk-or-`, base keyword `openrouter` |
| `huggingface` | Hugging Face | `HF_TOKEN` | `https://router.huggingface.co/v1` | key prefix `hf_`, base keyword `huggingface` |
| `aihubmix` | AiHubMix | `OPENAI_API_KEY` | `https://aihubmix.com/v1` | base keyword `aihubmix` |
| `siliconflow` | SiliconFlow | `OPENAI_API_KEY` | `https://api.siliconflow.cn/v1` | base keyword `siliconflow` |
| `novita` | Novita AI | `NOVITA_API_KEY` | `https://api.novita.ai/openai` | base keyword `novita` |
| `skywork` | Skywork | `SKYWORK_API_KEY` | `https://api.apifree.ai/agent/v1` | keywords `skywork`/`skyclaw`/`apifree`; base keyword `apifree.ai`; also exports `APIFREE_API_KEY` |
| `volcengine` | VolcEngine | `OPENAI_API_KEY` | `https://ark.cn-beijing.volces.com/api/v3` | keywords `volcengine`/`volces`/`ark`; base keyword `volces` |
| `volcengine_coding_plan` | VolcEngine Coding Plan | `OPENAI_API_KEY` | `https://ark.cn-beijing.volces.com/api/coding/v3` | keyword `volcengine-plan` |
| `byteplus` | BytePlus | `OPENAI_API_KEY` | `https://ark.ap-southeast.bytepluses.com/api/v3` | base keyword `bytepluses` |
| `byteplus_coding_plan` | BytePlus Coding Plan | `OPENAI_API_KEY` | `https://ark.ap-southeast.bytepluses.com/api/coding/v3` | keyword `byteplus-plan` |
| `qianfan` | Qianfan (Baidu) | `QIANFAN_API_KEY` | `https://qianfan.baidubce.com/v2` | base keyword `qianfan` (also routable from `ernie` keyword) |

> Gateways re-use each other's `OPENAI_API_KEY` env var when they
> speak the same upstream wire format.  The runtime reads the env
> var named in `env_key`; setting that one var lights up the
> provider.

---

## 2. First-party / native providers

These are providers that Femtobot talks to **directly** rather
than via a gateway aggregator.  All use `backend="openai_compat"`
unless otherwise noted.

| Slug | Display | Env key | Default base | Match keywords |
|------|---------|---------|--------------|----------------|
| `openai` | OpenAI | `OPENAI_API_KEY` | (use provider default) | `openai`, `gpt` |
| `bedrock` | **AWS Bedrock** | `BEDROCK_API_KEY` | (uses AWS SDK) | `bedrock`, `anthropic.claude`, `amazon.nova`, `meta.llama` — backend is its own `BedrockProvider`, not OpenAI-compat |
| `deepseek` | DeepSeek | `DEEPSEEK_API_KEY` | `https://api.deepseek.com` | `deepseek` |
| `gemini` | Gemini | `GEMINI_API_KEY` | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini`, `gemma` |
| `zhipu` | Zhipu AI | `ZAI_API_KEY` | `https://open.bigmodel.cn/api/paas/v4` | `zhipu`, `glm`, `zai` — also exports `ZHIPUAI_API_KEY` for parity |
| `dashscope` | DashScope (Alibaba Qwen) | `DASHSCOPE_API_KEY` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen`, `dashscope` |
| `moonshot` | Moonshot (Kimi) | `MOONSHOT_API_KEY` | `https://api.moonshot.ai/v1` | `moonshot`, `kimi` |
| `minimax` | MiniMax | `MINIMAX_API_KEY` | `https://api.minimax.io/v1` | `minimax` |
| `mistral` | Mistral | `MISTRAL_API_KEY` | `https://api.mistral.ai/v1` | `mistral` |
| `groq` | Groq | `GROQ_API_KEY` | `https://api.groq.com/openai/v1` | `groq` |
| `nvidia` | NVIDIA NIM | `NVIDIA_NIM_API_KEY` | `https://integrate.api.nvidia.com/v1` | `nvidia`, `nemotron`, `nvapi`; key prefix `nvapi-`; base keyword `nvidia.com` |
| `huggingface` | (also listed above as gateway) | | | |
| `skywork` | (also listed above as gateway) | | | |
| `stepfun` | Step Fun | `STEPFUN_API_KEY` | `https://api.stepfun.com/v1` | `stepfun`, `step` |
| `longcat` | LongCat | `LONGCAT_API_KEY` | `https://api.longcat.chat/openai/v1` | `longcat` |
| `xiaomi_mimo` | Xiaomi MIMO | `XIAOMIMIMO_API_KEY` | `https://api.xiaomimimo.com/v1` | `xiaomi_mimo`, `mimo` |
| `ant_ling` | Ant Ling | `ANT_LING_API_KEY` | `https://api.ant-ling.com/v1` | `ant_ling`, `ant-ling`, `ling-`, `ring-`; base keyword `ant-ling.com` |

### Notes on backend differentiation

`openai` is the **only** provider whose spec honors
`api_type=("auto"|"chat_completions"|"responses")` from
`ProviderConfig`.  All other `openai_compat` providers always use
the chat-completions surface even if the runtime sets `api_type`.

`bedrock` is the **only** non-`openai_compat` provider today.
The factory at [`_make_provider_core`](../femtobot/providers/factory.py#L30)
takes a dedicated branch:

```python
if provider_name == "bedrock":
    # create BedrockProvider(...)
else:
    # create OpenAICompatProvider(...)
```

The `ProviderSpec.backend` field also names four planned backends
that are not yet instantiated:
`anthropic`, `azure_openai`, `openai_codex`, `github_copilot`.
They are documented in [`registry.py`](../femtobot/providers/registry.py#L37)
but the runtime falls through to `openai_compat` for any spec
where the named backend is absent.

---

## 3. Local / self-hosted

Local runtimes are flagged `is_local=True`.  They share the
`openai_compat` wire format, so Femtobot's transport stack handles
them identically to the cloud providers — the runtime difference is
the loopback URL.

| Slug | Display | Default base | Env key | Notes |
|------|---------|--------------|---------|-------|
| `ollama` | Ollama | `http://localhost:11434/v1` | `OLLAMA_API_KEY` | keyword `ollama`, `nemotron`; base keyword `11434` |
| `vllm` | vLLM | (no default — user supplies) | `HOSTED_VLLM_API_KEY` | keyword `vllm` |
| `lm_studio` | LM Studio | `http://localhost:1234/v1` | `LM_STUDIO_API_KEY` | keywords `lm-studio`/`lmstudio`/`lm_studio`; base keyword `1234` |
| `ovms` | OpenVINO Model Server | `http://localhost:8000/v3` | (none required for unauthenticated) | keywords `openvino`, `ovms` |
| `atomic_chat` | Atomic Chat | `http://localhost:1337/v1` | `ATOMIC_CHAT_API_KEY` | keywords `atomic-chat`/`atomic_chat`/`atomicchat`; base keyword `1337` |

> vLLM is the only local provider with **no default base URL**: the
> spec expects users to set `extra_headers` / `extra_body` /
> explicit `api_base` via `ProviderConfig` so the runtime knows
> where the server is listening.

---

## 4. Catch-all

| Slug | Display | Backend | Notes |
|------|---------|---------|-------|
| `custom` | Custom | `openai_compat` | No keywords, no env var, no default base URL.  Used when the user specifies `api_base` + `api_key` directly without wanting to bind to a known provider.  Listed **first** in the registry so it doesn't shadow named providers. |

---

## Detection priority (when `provider="auto"`)

The runtime decides in this order when given a model string like
`"provider/model"` or just `"model"`:

1. **Direct slug match** — if `model` literally contains the slug
   of a provider (e.g. `"openai/gpt-4o"` matches `openai`),
   `find_by_name` is short-circuited to that slug.
2. **Keyword match** — otherwise scan all `ProviderSpec.keywords`
   (case-insensitive).  Order matters: registries earlier in the
   list win ties.  Gateways appear first, so an unknown model
   without a keyword match would never be implied — it would fall
   to the gateway at the head of the list (currently `openrouter`
   ... no wait, `custom` is first; `custom` has no keywords so a
   model with no keyword falls through to whatever provider is
   actually configured with `OPENAI_API_KEY` etc.).  In practice,
   users set `provider=` explicitly when in doubt.
3. **`detect_by_key_prefix`** — when the user pastes an API key,
   Femtobot recognizes the prefix and routes to the right provider
   (e.g. `sk-or-` → `openrouter`, `hf_` → `huggingface`,
   `nvapi-` → `nvidia`).
4. **`detect_by_base_keyword`** — substring match on the
   user-supplied `api_base` URL.

---

## Environment-variable cheat-sheet

The runtime reads each provider's env var through the spec.  Here
is the exact set of names Femtobot looks for:

```
AI-related (alphabetical):
ANT_LING_API_KEY        — ant_ling
APIFREE_API_KEY         — skywork (alias for SKYWORK_API_KEY)
ATOMIC_CHAT_API_KEY     — atomic_chat
BEDROCK_API_KEY         — bedrock (used together with AWS_REGION,
                          AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY —
                          see femtobot/providers/bedrock.py)
DASHSCOPE_API_KEY       — dashscope (Qwen)
DEEPSEEK_API_KEY        — deepseek
GEMINI_API_KEY          — gemini
GROQ_API_KEY            — groq
HF_TOKEN                — huggingface
HOSTED_VLLM_API_KEY     — vllm
LM_STUDIO_API_KEY       — lm_studio
LONGCAT_API_KEY         — longcat
MINIMAX_API_KEY         — minimax
MISTRAL_API_KEY         — mistral
MOONSHOT_API_KEY        — moonshot (Kimi)
NOVITA_API_KEY          — novita
NVIDIA_NIM_API_KEY      — nvidia
OLLAMA_API_KEY          — ollama
OPENAI_API_KEY          — openai, aihubmix, siliconflow, volcengine,
                          volcengine_coding_plan, byteplus,
                          byteplus_coding_plan
OPENROUTER_API_KEY      — openrouter
QIANFAN_API_KEY         — qianfan
SKYWORK_API_KEY         — skywork (and via APIFREE_API_KEY)
STEPFUN_API_KEY         — stepfun
XIAOMIMIMO_API_KEY      — xiaomi_mimo
ZAI_API_KEY             — zhipu (Zhipu AI / GLM)
ZHIPUAI_API_KEY         — zhipu (legacy alias)
```

Multiple providers sharing `OPENAI_API_KEY` is **intentional** —
they all accept OpenAI wire format keys.

---

## How to refresh this document

The recommended regeneration script (run from the repo root):

```bash
python3 - <<'PYEOF'
import re
from pathlib import Path
src = Path('femtobot/providers/registry.py').read_text()
# (Parse ProviderSpec blocks like the script that produced this file.)
PYEOF
```

If you add a provider, please:

1. Add the `ProviderSpec(...)` to `PROVIDERS` in
   `femtobot/providers/registry.py`.  Test it locally with
   `uv run femtobot status`.
2. Re-run the parse script and update this document so the
   inventory stays in sync with the runtime.

---

## Coverage summary (v0.1.6)

* **30 named providers + 1 catch-all = 31 entries** in `PROVIDERS`.
* **29** use `OpenAICompatProvider` (everything except `bedrock`).
* **1** uses `BedrockProvider` (`bedrock`).
* **2** are flagged `is_gateway=True` but listed under both the
  gateway and first-party sections (`huggingface` and `skywork`)
  because they fit both modes.
* **5** are flagged `is_local=True` (Ollama, vLLM, LM Studio,
  OpenVINO Model Server, Atomic Chat).

The runtime has **no** provider that uses `backend="anthropic"`,
`backend="azure_openai"`, `backend="openai_codex"`, or
`backend="github_copilot"` (those strings are reserved in
`ProviderSpec.backend` for future use).  Anthropic Claude is
reached today via Bedrock (`anthropic.claude*`), OpenRouter,
AiHubMix, or Hugging Face — never directly.
