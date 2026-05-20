#!/usr/bin/env python3
"""Launch the Jira MCP server from a user-level MCP config.

This keeps the project .mcp.json secret-free while still making the Jira
server resolvable from the repo configuration.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


CONFIG_CANDIDATES = (
    Path(os.environ.get("JIRA_MCP_CONFIG_PATH", "")).expanduser()
    if os.environ.get("JIRA_MCP_CONFIG_PATH")
    else None,
    Path.home() / ".claude" / "mcp.json",
    Path.home() / ".codex" / "mcp.json",
    Path.home() / ".config" / "opencode" / "mcp.json",
)


def _resolve_env_value(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("Jira MCP env values must be strings")

    if value.startswith("${") and value.endswith("}"):
        key = value[2:-1]
        resolved = os.environ.get(key)
        if not resolved:
            raise RuntimeError(f"Missing required environment variable: {key}")
        return resolved

    return value


def _load_jira_server_config() -> tuple[str, list[str], dict[str, str]]:
    for candidate in CONFIG_CANDIDATES:
        if candidate is None:
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        server = (data.get("mcpServers") or {}).get("jira")
        if not isinstance(server, dict):
            continue

        command = server.get("command")
        args = server.get("args", [])
        env = server.get("env", {})
        if not isinstance(command, str) or not isinstance(args, list):
            continue
        if not isinstance(env, dict):
            env = {}

        resolved_env = dict(os.environ)
        for key, value in env.items():
            if isinstance(key, str):
                resolved_env[key] = _resolve_env_value(value)

        return command, [str(arg) for arg in args], resolved_env

    raise FileNotFoundError(
        "Could not find a usable jira MCP config in ~/.claude/mcp.json, "
        "~/.codex/mcp.json, or ~/.config/opencode/mcp.json"
    )


def main() -> int:
    command, args, env = _load_jira_server_config()
    os.execvpe(command, [command, *args], env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
