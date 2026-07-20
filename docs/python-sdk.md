# Python SDK

You can interact with femtobot programmatically from Python. Since femtobot is CLI-first, the most robust way to use it from Python scripts is via subprocesses invoking the CLI.

## Quick Start

You can import femtobot and use the `subprocess` module to call the CLI agent programmatically.

```python
import subprocess

def run_agent(message: str, suffix: str = None) -> str:
    cmd = ["femtobot", "agent", "-m", message]
    if suffix:
        cmd.extend(["--suffix", suffix])
        
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True
    )
    return result.stdout.strip()

# Run the agent
response = run_agent("What is the capital of France?")
print(response)
```

## Advanced Patterns

### Background Server

You can also programmatically start the API server and then use the standard `openai` python package to communicate with the agent.

```python
import subprocess
import time
from openai import OpenAI

# Start the server in the background
server_process = subprocess.Popen(["femtobot", "serve"])

# Wait a moment for the server to bind
time.sleep(2)

try:
    client = OpenAI(
        base_url="http://127.0.0.1:8900/v1",
        api_key="dummy",
    )

    resp = client.chat.completions.create(
        model="femtobot",
        messages=[{"role": "user", "content": "Hello!"}],
    )
    print("Agent says:", resp.choices[0].message.content)

finally:
    # Always clean up the server process
    server_process.terminate()
    server_process.wait()
```

### Library Import

If a `Femtobot` class is exported in the future, you may also import it directly:
```python
import femtobot
# Wait for stable Python API release for direct class instantiation.
```
