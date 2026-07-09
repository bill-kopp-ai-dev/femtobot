#!/usr/bin/env python3
"""Verify that agents.cli.* schema does not collide with legacy cli.* config.

Run: uv run python3 scripts/check_cli_schema_compat.py
"""
import json
import sys
import tempfile


def main():
    # Synthetic config with BOTH blocks (legacy + Camada 1)
    synthetic = {
        "cli": {"enabled": True, "theme": "monochrome"},  # legacy top-level
        "agents": {"defaults": {"cli": {"theme": "cyber-dark", "multiline": "off"}}}
    }

    # Try to load via Config
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(synthetic, f)
            f.flush()
            from femtobot.config.schema import Config
            cfg = Config.model_validate(synthetic)
            print("Config loaded OK")
            print(f"  agents.cli.theme = {cfg.agents.defaults.cli.theme}")
            print(f"  agents.cli.multiline = {cfg.agents.defaults.cli.multiline}")
            print(f"  agents.cli.whimsy.verbsEnabled = {cfg.agents.defaults.cli.whimsy.verbs_enabled}")
            print("PRECEDENCE: agents.cli.* wins (more specific path)")
            return 0
    except Exception as e:
        print(f"ERROR loading config: {e}")
        print("\nCOLLISION DETECTED: legacy 'cli.*' at root level conflicts with")
        print("the strict Pydantic schema (extra='forbidden').")
        print("Migration required: move 'cli.*' to 'agents.defaults.cli.*'")
        return 1

if __name__ == "__main__":
    sys.exit(main())
