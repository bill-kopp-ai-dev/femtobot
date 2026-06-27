# Security Model

Femtobot is a CLI agent that executes shell commands, reads/writes files, and
calls arbitrary LLM providers. It also accepts tool calls from MCP servers and
runs them in-process. None of that is safe by default — every layer of
authority has to be deliberate.

This page inventories the security boundaries, the knobs that govern each,
and the threats Femtobot is **not** trying to defend against.

---

## Trust model

| Surface | Trust level | Mitigations |
|---|---|---|
| Local CLI user | Trusted (you) | Nothing — the CLI runs with your full UID. |
| `config.json` | Trusted (you) | Loaded once at startup; env-var interpolation gated by `os.environ`. |
| Workspace files | Mixed (yours + repo contents) | Sandbox, deny patterns, path guards. |
| LLM provider responses | **Untrusted** | Treated as data, never as code. JSON-schema validation on tool calls. |
| MCP server responses | **Untrusted** | Same as provider. Wrapped in isolated async tasks. |
| Web search/fetch results | **Untrusted** | Treated as text, never as instructions. SSRF guard on outbound HTTP. |
| Remote HTTP clients (A2A peers) | Mixed | Bound to `127.0.0.1` by default. |
| Slash commands | Trusted (you) | Routed through the explicit `command/router.py`. |

> The agent is not a sandbox. If you point Femtobot at a workspace that contains
> secrets and give it `exec` access, a prompt-injection in any source (file
> read, web fetch, MCP tool result) can pivot to `cat ~/.ssh/id_rsa`. Treat
> the workspace as the boundary of authority.

---

## File-system boundaries

### `tools.restrictToWorkspace`

Policy intent flag. When `true`, tools refuse to read or write paths outside
the resolved workspace (`agents.defaults.workspace`). When `false` (default),
tools can read/write anywhere on the filesystem the user can.

Even at `false`, certain operations stay gated:

- `write_file` and `edit_file` validate the resolved path is within the
  workspace or a permitted absolute path.
- `apply_patch` enforces the same.
- `read_file` is unrestricted by default (the agent needs to read system
  files to be useful) — combine with a deny list if you need stricter behavior.

### `tools.exec.pathAppend` / `tools.exec.allowedEnvKeys`

Controls what extra `PATH` entries and env-var names are passed to the child
process. Default `allowedEnvKeys: []` blocks everything except a small
allow-list (PATH, HOME, LANG, …). Use this to keep secrets out of subprocesses.

### Sandbox backends

`tools.exec.sandbox` (string, default `""`) names a backend that wraps each
command. Femtobot ships with no backend wired by default, but the convention
is:

- `bubblewrap` (Linux, recommended)
- `firejail` (Linux)
- `docker` (Linux, Mac via colima, Windows via WSL2)

Example:

```json
{
  "tools": {
    "exec": {
      "enable": true,
      "sandbox": "bubblewrap",
      "allowPatterns": ["^python\\b", "^pytest\\b"],
      "denyPatterns": ["^rm\\b", "^sudo\\b"]
    }
  }
}
```

---

## Command guard

`DESTRUCTIVE_DENY_PATTERNS` (in `femtobot/agent/tools/shell.py`) is the
built-in blocklist for obviously destructive commands. It is regex-based and
case-sensitive. The defaults include:

- `^rm\s+-rf\s+/$`
- `^mkfs\b`
- `^dd\s+.*\s+of=/dev/`
- `^chmod\s+-R\s+777\s+/$`
- `^>\s*/dev/sd[a-z]`
- And others targeting common foot-guns

You can extend with `tools.exec.denyPatterns` (additive, applied after the
built-ins). You cannot shrink the built-in list today — there is no
`allowPatterns`-only mode at the config level. If you need a strictly positive
allow-list, set the sandbox backend to `docker` and pass `--security-opt
no-new-privileges` plus a minimal image.

> **Bypass caveat.** The command guard operates on the literal command string
> the agent submits. A creative agent (or one following injected instructions
> from a web fetch) can construct destructive commands by composing multiple
> `exec` calls, piping through `sh`, or using shell variables. The sandbox
> backend is the real boundary; the deny list is a hint, not a guarantee.

---

## SSRF guard

`web_fetch` (and any future HTTP tool) validates outbound URLs against a
private-IP blocklist:

- `127.0.0.0/8` (loopback) — allowed only if `tools.webuiAllowLocalServiceAccess` is `true`
- `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` (RFC 1918)
- `169.254.0.0/16` (link-local, includes cloud metadata!)
- `fc00::/7` (IPv6 ULA)
- `fe80::/10` (IPv6 link-local)

Override with `tools.ssrfWhitelist` (list of CIDR strings):

```json
{
  "tools": {
    "ssrfWhitelist": ["100.64.0.0/10"],
    "webuiAllowLocalServiceAccess": false
  }
}
```

Common reasons to add a range:

- Tailscale (`100.64.0.0/10`)
- Internal services on a corporate VPN
- Local services you trust explicitly (use `127.0.0.1` only)

> **Cloud metadata.** AWS, GCP, and Azure all expose instance metadata on
> `169.254.169.254`. The SSRF guard blocks this by default. If you actually
> need IMDSv2 access, whitelist `169.254.169.254` explicitly and read the
> [AWS docs on IMDSv2 token requirements](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configure-instance-metadata-service.html).

---

## Provider and tool credentials

### Where secrets live

All secrets are stored in `config.json` under the relevant provider's
`apiKey` field. Plain text. The schema does **not** encrypt the file — that's
your filesystem's job (`chmod 600`, full-disk encryption, etc.).

### Env-var interpolation

To keep secrets out of the file, use `${VAR}` references:

```json
{ "providers": { "openai": { "apiKey": "${OPENAI_API_KEY}" } } }
```

`femtobot/config/loader.py:resolve_config_env_vars()` substitutes on load.
Missing variables raise `ValueError` (loud, fast).

### `self` tool redaction

The `my` tool redacts any sub-field whose name matches
`_SENSITIVE_NAMES` (`api_key`, `token`, `password`, `secret`, `authorization`,
…). So even a successful prompt injection that asks the agent to
"self(action=check, key=providers)" gets back `"<redacted>"` for every API
key. See [my-tool.md](./my-tool.md#security).

---

## Network exposure

| Surface | Default bind | Auth | Recommendation |
|---|---|---|---|
| `femtobot agent` | n/a (TTY) | None | Local-only. |
| `femtobot serve` | `127.0.0.1:8900` | **None** | Use a reverse proxy with TLS + auth if exposing beyond localhost. |
| `femtobot gateway` | `127.0.0.1:8765` | None | Stage 2 placeholder. Treat as `serve`. |
| `websocket` channel | `127.0.0.1:8765` (default) | Optional token via `channels.websocket.token` | See [websocket.md](./websocket.md#security). |

The `websocket` channel is the only ingress that has any auth primitive
built in. `serve` and `gateway` have **zero auth** — they're plain HTTP on
loopback. Anything you do beyond loopback is on you.

---

## MCP server isolation

Each MCP server runs as a child process under the agent's UID. The boundary
is process isolation, not user isolation:

- A malicious MCP server can read any file you can read.
- A malicious MCP server can launch additional subprocesses.
- A malicious MCP server can saturate the loop with tool-call traffic until
  `agents.defaults.maxToolIterations` kicks in.

Mitigations you can apply:

- Run the agent as a dedicated, low-privilege user.
- Set `tools.mcpServers.<name>.enabledTools` to the minimum allow-list.
- Run the agent in a Docker container with `--read-only` /
  `--security-opt no-new-privileges` / `--cap-drop ALL`.
- Use the `webuiAllowLocalServiceAccess: false` default to prevent SSRF
  pivots through the local web UI.

---

## Logging and audit

Femtobot emits structured logs via `loguru`. Default level is `INFO`. Enable
verbose logging with `femtobot --verbose` or
`femtobot serve --verbose`.

Recommended log destinations:

- A rotating file in the instance directory:
  `LOGURU_FILE = /home/me/.femtobot/logs/femtobot.log`.
- A syslog forwarder for centralized collection.
- A SIEM if you run Femtobot in a multi-tenant setup.

What gets logged:

- Every LLM call (model, prompt size, response size, latency).
- Every tool call (tool name, arguments, result size, exit code).
- Every config load (file path, version).
- Every Dream consolidation commit (commit SHA, files touched).

What does **not** get logged:

- Tool arguments that match `_SENSITIVE_NAMES` (filtered before log).
- Provider responses that exceed `maxToolResultChars` (truncated to a
  placeholder).

---

## Threat model — what Femtobot does NOT defend against

| Threat | Defense |
|---|---|
| Adversarial user running the CLI | None — by design. |
| Adversarial LLM following attacker-injected instructions | Partial — `_DENIED_ATTRS`, command guard, SSRF guard. |
| Adversarial MCP server reading arbitrary files | None — run in a sandboxed user / container. |
| Network attacker on the LAN intercepting `serve` HTTP traffic | None — bind to loopback or use TLS termination. |
| Adversarial web page feeding prompt injection via `web_fetch` | Partial — content is treated as text, but if you `apply_patch` on its suggestion you accept the consequences. |
| Adversarial config.json supplied by a third party | None — config is fully trusted. Review before deploying. |
| Filesystem-level keylogger or screen capture | None — run on a trusted machine. |

---

## Hardening checklist

For production-ish deployments:

- [ ] Run Femtobot as a dedicated, low-privilege user.
- [ ] `chmod 600` the `config.json` file.
- [ ] Use `${VAR}` interpolation for every secret.
- [ ] Set `tools.restrictToWorkspace: true`.
- [ ] Set `tools.exec.sandbox` to `bubblewrap` / `firejail` / `docker`.
- [ ] Add `tools.exec.denyPatterns` for your environment's foot-guns.
- [ ] Set `tools.ssrfWhitelist` to exactly the ranges you need.
- [ ] Use `tools.mcpServers.<name>.enabledTools` to lock MCP surfaces.
- [ ] Bind `serve` / `gateway` to `127.0.0.1`; put a TLS + auth proxy in front
      if exposing beyond loopback.
- [ ] Set `agents.defaults.unifiedSession: false` unless you really need it.
- [ ] Set `agents.defaults.sessionTtlMinutes > 0` to compact idle sessions.
- [ ] Forward logs to a SIEM.
- [ ] Periodically run `git log` in `workspace/memory/.git/` to audit Dream
      consolidation activity.

---

## See also

- [configuration.md](./configuration.md) — every security-relevant knob
- [my-tool.md](./my-tool.md) — the runtime-introspection tool's own security
  layers
- [websocket.md](./websocket.md) — websocket-specific auth
- [tools.md](./tools.md) — what each native tool can do (and therefore,
  what an attacker can do via prompt injection)
- [troubleshooting.md](./troubleshooting.md) — when the SSRF guard blocks
  legitimate traffic