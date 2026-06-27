# Deployment

This page covers local install, Docker, and running Femtobot as a long-lived
service under systemd or supervisord. For multi-instance patterns, see
[multiple-instances.md](./multiple-instances.md).

---

## Local Installation

The recommended way to deploy and run Femtobot is by installing it via `uv` or
`pip`, or by running it from a source checkout.

**Using uv (tool install, isolated binary):**
```bash
uv tool install femtobot
femtobot --version
```

**Using uv (from source, dev-friendly):**
```bash
git clone https://github.com/bill-kopp-ai-dev/femtobot.git
cd femtobot
uv sync
uv run femtobot --version
```

**Using pip (editable, for hacking):**
```bash
git clone https://github.com/bill-kopp-ai-dev/femtobot.git
cd femtobot
pip install -e .
femtobot --version
```

After any of the above, the `femtobot` binary lives on your `$PATH` (or in the
project's `.venv/bin/`). If you used `uv sync` without `uv tool install`,
always prefix with `uv run` so the local checkout is used.

---

## Docker

Run Femtobot in a container and mount the instance directory from the host so
the config and workspace persist across container restarts.

**Example `Dockerfile` (minimal):**
```dockerfile
FROM python:3.11-slim

RUN pip install --no-cache-dir femtobot
WORKDIR /home/femtobot
USER femtobot

ENTRYPOINT ["femtobot"]
CMD ["serve", "--host", "0.0.0.0"]
```

**Build and run:**
```bash
# Build
docker build -t femtobot .

# Initialize config on the host (one-time)
docker run --rm -v ~/.femtobot:/home/femtobot/.femtobot femtobot onboard
# Edit on host to add API keys
$EDITOR ~/.femtobot/config.json

# Run a single-shot query
docker run --rm -v ~/.femtobot:/home/femtobot/.femtobot femtobot \
  agent -m "Hello!"

# Run the OpenAI-compatible API server, exposing api.port
docker run -d --name femtobot-serve \
  -v ~/.femtobot:/home/femtobot/.femtobot \
  -p 8900:8900 \
  femtobot serve --host 0.0.0.0

# Run the gateway (Stage 2 placeholder)
docker run -d --name femtobot-gw \
  -v ~/.femtobot:/home/femtobot/.femtobot \
  -p 8765:8765 \
  femtobot gateway
```

> **Bind addresses.** Inside a container, `127.0.0.1` is the container's own
> loopback — the host cannot reach it. Always pass `--host 0.0.0.0` to
> `serve`/`gateway` when running in Docker, and publish the port with `-p`.

> **Persistent volume.** The `-v ~/.femtobot:/home/femtobot/.femtobot` mount
> is what keeps your config and workspace alive. Forget it and you'll start
> fresh on every container restart.

---

## Linux Service (systemd, user mode)

Run Femtobot as a systemd user service so it starts on login and restarts on
failure.

**1. Create the service file** at `~/.config/systemd/user/femtobot-serve.service`:

```ini
[Unit]
Description=Femtobot OpenAI-compatible API server
After=network.target

[Service]
Type=simple
# Adjust the path to the femtobot executable on your system:
#   - If you installed via `uv tool install femtobot`, it's on $HOME/.local/bin
#   - If you cloned the source, use `uv run --project /abs/path/femtobot femtobot`
#   - If you installed via `pip install --user`, it's on $HOME/.local/bin
ExecStart=%h/.local/bin/femtobot serve --host 127.0.0.1 --port 8900
Restart=on-failure
RestartSec=10

# Hardening (recommended)
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=%h/.femtobot

[Install]
WantedBy=default.target
```

**2. Reload systemd and start the service:**

```bash
systemctl --user daemon-reload
systemctl --user enable --now femtobot-serve
systemctl --user status femtobot-serve
journalctl --user -u femtobot-serve -f
```

**3. (Optional) Lingering, so the service runs without an active session:**

```bash
sudo loginctl enable-linger $USER
```

> **Common pitfall.** The `ExecStart` path in older docs (`/path/to/femtobot`)
> does not exist. Use either `%h/.local/bin/femtobot` (after `uv tool install`),
> or the absolute path to the `femtobot` script inside the source checkout's
> `.venv/bin/`. Run `which femtobot` to confirm.

> **Multi-instance.** To run two services side by side, create a second unit
> (`femtobot-serve-dev.service`) pointing at a different `--folder-path` /
> `--suffix` and a different `--port`.

---

## supervisord alternative

If you don't use systemd, `supervisord` works just as well:

```ini
[program:femtobot-serve]
command=%(env_HOME)s/.local/bin/femtobot serve --host 127.0.0.1 --port 8900
autostart=true
autorestart=true
startretries=3
stderr_logfile=/var/log/femtobot.err.log
stdout_logfile=/var/log/femtobot.out.log
user=youruser
environment=HOME="%(env_HOME)s"
```

Reload: `supervisorctl reread && supervisorctl update`.

---

## Reverse proxy (TLS termination)

`femtobot serve` is plain HTTP. To expose it over HTTPS, terminate TLS at a
reverse proxy. Example for `caddy`:

```caddy
femtobot.example.com {
    reverse_proxy 127.0.0.1:8900
    basicauth {
        alice $2a$14$<bcrypt-hash>
    }
}
```

For `nginx`:

```nginx
server {
    listen 443 ssl;
    server_name femtobot.example.com;

    ssl_certificate     /etc/letsencrypt/live/femtobot.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/femtobot.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8900;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;

        # SSE: disable proxy buffering so deltas stream
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 24h;
    }
}
```

See [security.md](./security.md) for the auth/authz story (currently: the
server has none; the proxy is the only line of defense).

---

## Health checks

`GET /health` returns `{"status": "ok"}` once the agent loop is initialized.
Use it for liveness probes in Docker / Kubernetes:

```yaml
# docker-compose.yml
services:
  femtobot:
    image: femtobot
    command: ["serve", "--host", "0.0.0.0"]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8900/health"]
      interval: 30s
      timeout: 5s
      retries: 3
```

There is **no readiness probe distinction** today — `/health` is up as soon as
aiohttp binds, even if the underlying provider is slow to respond on the first
request. Add your own warm-up if that matters to your SLA.

---

## See also

- [configuration.md](./configuration.md) — `api.host`, `api.port`, `api.timeout`
- [openai-api.md](./openai-api.md) — what `femtobot serve` actually exposes
- [multiple-instances.md](./multiple-instances.md) — running multiple instances
  on one host
- [security.md](./security.md) — TLS, auth, network exposure
- [troubleshooting.md](./troubleshooting.md) — common deployment pitfalls