#!/usr/bin/env python3
"""Invoke Claude Code as a subprocess for delegation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class InvokerConfig:
    model: str
    effort: str
    permission_mode: str
    mcp_mode: str
    subagent_mode: str
    heartbeat_seconds: int
    output_mode: str
    prompt: str


def generate_mcp_config(mcp_mode: str, source_config_path: str | None) -> tuple[list[str], str | None]:
    if mcp_mode == "all":
        return ([], None)

    if mcp_mode == "none":
        config_json = json.dumps({"mcpServers": {}})
        return (["--strict-mcp-config", "--mcp-config", config_json], config_json)

    if source_config_path is None:
        raise ValueError(f"MCP mode '{mcp_mode}' requires a source config path")

    source = Path(source_config_path)
    if not source.exists():
        raise ValueError(f"MCP config not found: {source}")

    config = json.loads(source.read_text(encoding="utf-8"))
    mcp_servers = config.get("mcpServers", {})
    if mcp_mode not in mcp_servers:
        raise ValueError(f"MCP server '{mcp_mode}' not found in {source}")

    server_config = dict(mcp_servers[mcp_mode])
    env_vars = server_config.pop("env", None)
    if isinstance(env_vars, dict):
        for k, v in env_vars.items():
            if k not in os.environ:
                os.environ[k] = v
    config_json = json.dumps({"mcpServers": {mcp_mode: server_config}})
    return (["--strict-mcp-config", "--mcp-config", config_json], None)


def start_heartbeat(interval_seconds: int, model: str, effort: str, mcp_mode: str, output_mode: str) -> threading.Thread | None:
    if interval_seconds == 0:
        return None

    def _heartbeat():
        while True:
            threading.Event().wait(interval_seconds)
            print(
                f"Claude Code still running: model={model} effort={effort} mcp={mcp_mode} mode={output_mode}",
                file=sys.stderr,
                flush=True,
            )

    # daemon=True so the heartbeat dies with the parent process — no explicit stop needed
    t = threading.Thread(target=_heartbeat, daemon=True)
    return t


def invoke_claude(config: InvokerConfig) -> subprocess.CompletedProcess[Any]:
    args: list[str] = [
        "claude",
        "-p",
        "--model", config.model,
        "--effort", config.effort,
        "--permission-mode", config.permission_mode,
    ]

    if config.subagent_mode == "off":
        args.extend(["--disallowedTools", "Task Agent"])

    source_path: str | None = None
    if config.mcp_mode not in ("all", "none"):
        env_path = os.environ.get("CLAUDE_DELEGATE_MCP_CONFIG_PATH")
        source_path = env_path or str(Path(".mcp.json"))

    mcp_args, mcp_config_path = generate_mcp_config(config.mcp_mode, source_path)
    cleanup_files: list[str] = []
    if mcp_config_path and config.mcp_mode not in ("all", "none"):
        cleanup_files.append(mcp_config_path)

    try:
        if config.output_mode == "stream":
            args.extend(mcp_args)
            args.extend([
                "--verbose",
                "--output-format", "stream-json",
                "--include-partial-messages",
            ])
            return subprocess.run(
                [*args, config.prompt],
                capture_output=True,
                text=True,
            )

        args.extend(mcp_args)
        args.extend(["--output-format", "json"])
        return subprocess.run(
            [*args, config.prompt],
            capture_output=True,
            text=True,
        )
    finally:
        for f in cleanup_files:
            try:
                Path(f).unlink()
            except OSError:
                pass
