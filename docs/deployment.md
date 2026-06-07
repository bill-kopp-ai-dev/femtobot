# Deployment

## Local Installation

The recommended way to deploy and run femtobot is by installing it via `uv` or `pip`.

**Using uv (Recommended):**
```bash
uv sync
```

**Using pip:**
```bash
pip install -e .
```

## Docker

You can run femtobot in a Docker container. Make sure to mount your instance directory to persist the configuration and workspace.

```bash
# Build the image
docker build -t femtobot .

# Initialize config (first time only)
docker run -v ~/.femtobot:/home/femtobot/.femtobot --rm femtobot onboard

# Edit config on host to add API keys
vim ~/.femtobot/config.json

# Run a single command
docker run -v ~/.femtobot:/home/femtobot/.femtobot --rm femtobot agent -m "Hello!"

# Run gateway
docker run -v ~/.femtobot:/home/femtobot/.femtobot -p 8765:8765 femtobot gateway
```

## Linux Service (Systemd)

Run femtobot as a systemd user service so it starts automatically and restarts on failure.

**1. Create the service file** at `~/.config/systemd/user/femtobot-serve.service` (replace paths as needed):

```ini
[Unit]
Description=Femtobot Server
After=network.target

[Service]
Type=simple
ExecStart=/path/to/femtobot serve
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
```

**2. Enable and start:**

```bash
systemctl --user daemon-reload
systemctl --user enable --now femtobot-serve
```
