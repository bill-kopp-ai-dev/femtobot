# Quick Start

Welcome to femtobot! For more detailed overview information, please check the main [README.md](../README.md).

## Installation

**Install with uv (Recommended)**
```bash
uv tool install femtobot-ai
```

**Install with pip**
```bash
pip install femtobot-ai
```

**Install from source**
```bash
git clone https://github.com/HKUDS/femtobot.git
cd femtobot
uv sync
```

## Your First Run

**1. Initialize the instance**

Set up your default configuration and workspace:
```bash
femtobot onboard
```

**2. Chat with the agent**

Start an interactive chat session:
```bash
femtobot agent
```

Or send a single message directly:
```bash
femtobot agent -m "Hello femtobot!"
```

That's it! You have a working CLI-first AI agent.
