#!/usr/bin/env python3
"""Invoke OpenCode as a subprocess for delegation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from logger import get_logger
from heartbeat import start_heartbeat

logger = get_logger("opencode_invoker")

ALLOWED_MODELS: frozenset[str] = frozenset()

OPENCODE_ENV_KEYS = (
    "OPENCODE_CONFIG",
    "OPENCODE_CONFIG_DIR",
    "OPENCODE_CONFIG_CONTENT",
    "OPENCODE_GIT_BASH_PATH",
    "OPENCODE_PERMISSION",
    "OPENCODE_SERVER_PASSWORD",
    "OPENCODE_SERVER_USERNAME",
)


@dataclass
class OpenCodeInvokerConfig:
    model: str
    permission_mode: str
    mcp_mode: str
    subagent_mode: str
    heartbeat_seconds: int
    output_mode: str
    prompt: str
    inactivity_timeout: int = 0


def load_opencode_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Build child env, backfilling OpenCode settings env when sandbox hooks fail."""
    child_env = dict(base_env or os.environ)

    for path in (
        Path.home() / ".config" / "opencode" / "config.json",
        Path.home() / ".config" / "opencode" / "config.local.json",
        Path.cwd() / "opencode.json",
        Path.cwd() / "opencode.jsonc",
    ):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        env = data.get("env")
        if not isinstance(env, dict):
            continue

        for key, value in env.items():
            if isinstance(key, str) and isinstance(value, (str, int, float, bool)):
                child_env.setdefault(key, str(value))

    return child_env


def _normalize_model(model: str) -> str:
    """Strip provider prefix and context-window suffix for comparison."""
    raw = model.lower().strip()
    for prefix in ("opencode/", "zen/", "deepseek/", "qwen/"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
    # Strip Claude Code context-window suffix like [1m], [200k]
    bracket_pos = raw.find("[")
    if bracket_pos != -1:
        raw = raw[:bracket_pos]
    return raw


CLAUDE_CODE_MODEL_MAP: dict[str, str] = {
    "deepseek-v4-flash": "deepseek/deepseek-v4-flash",
    "deepseek-v4-flash-free": "deepseek/deepseek-v4-flash",
    "deepseek-v4-pro": "deepseek/deepseek-chat",
    "deepseek-v4-pro-free": "deepseek/deepseek-chat",
    "claude-sonnet-4": "deepseek/deepseek-v4-flash",
    "claude-sonnet-4-6": "deepseek/deepseek-v4-flash",
    "claude-haiku-4": "deepseek/deepseek-v4-flash",
    "claude-opus-4": "deepseek/deepseek-chat",
}


def _map_model_for_opencode(model: str) -> str:
    """Map Claude Code model IDs to OpenCode provider/model format."""
    if "/" in model:
        return model
    base = _normalize_model(model)
    mapped = CLAUDE_CODE_MODEL_MAP.get(base)
    if mapped:
        return mapped
    if base.startswith("deepseek"):
        return f"deepseek/{base}"
    return f"deepseek/{base}"


def _validate_model(model: str) -> str:
    """Pass through the model string — provider prefix determines routing."""
    if not model:
        return "opencode/qwen3.6-plus-free"
    if not ALLOWED_MODELS:
        return _map_model_for_opencode(model)
    base = _normalize_model(model)
    if "/" not in base:
        return f"opencode/{base}"
    return model


def build_opencode_args(config: OpenCodeInvokerConfig) -> list[str]:
    """Build the opencode run command arguments."""
    model = _validate_model(config.model)
    args: list[str] = [
        "opencode",
        "run",
        "--format", "json",
        "--model", model,
    ]

    if config.permission_mode == "bypassPermissions":
        args.append("--dangerously-skip-permissions")

    if config.subagent_mode == "on":
        args.append("--agent")

    return args


def launch_opencode_async(
    config: OpenCodeInvokerConfig,
    stdout_path: str,
    stderr_path: str,
) -> "subprocess.Popen[Any]":
    """Launch OpenCode in the background with stdout/stderr written to files."""
    args = build_opencode_args(config)
    child_env = load_opencode_env()

    stdout_fh = open(stdout_path, "w", encoding="utf-8")
    stderr_fh = open(stderr_path, "w", encoding="utf-8")

    return subprocess.Popen(
        [*args, config.prompt],
        stdin=subprocess.DEVNULL,
        stdout=stdout_fh,
        stderr=stderr_fh,
        env=child_env,
        text=True,
    )


def invoke_opencode(config: OpenCodeInvokerConfig) -> subprocess.CompletedProcess[Any]:
    logger.info(
        "starting opencode invocation",
        model=config.model,
        mcp_mode=config.mcp_mode,
    )

    args = build_opencode_args(config)
    child_env = load_opencode_env()

    if config.output_mode == "stream":
        # OpenCode doesn't have a stream-json mode; fall back to default format
        pass

    process = subprocess.Popen(
        [*args, config.prompt],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=child_env,
        text=True,
    )

    stdout_lines: list[str] = []
    last_activity = time.monotonic()
    stdout_lock = threading.Lock()

    def _read_stdout():
        nonlocal last_activity
        for line in process.stdout:  # type: ignore[union-attr]
            with stdout_lock:
                stdout_lines.append(line)
                last_activity = time.monotonic()

    reader = threading.Thread(target=_read_stdout, daemon=True)
    reader.start()

    monitor = start_heartbeat(
        interval_seconds=config.heartbeat_seconds,
        process=process,
        inactivity_timeout=config.inactivity_timeout,
        get_last_activity=lambda: last_activity,
        extra_fields={
            "model": config.model,
            "mcp": config.mcp_mode,
            "mode": config.output_mode,
        },
        prefix="OpenCode",
    )
    if monitor:
        monitor.start()

    process.wait()
    reader.join(timeout=5)
    if monitor:
        monitor.join(timeout=5)

    with stdout_lock:
        stdout = "".join(stdout_lines)
    stderr_output = process.stderr.read() if process.stderr else ""

    return subprocess.CompletedProcess(
        args=[*args, config.prompt],
        returncode=process.returncode,
        stdout=stdout,
        stderr=stderr_output,
    )
