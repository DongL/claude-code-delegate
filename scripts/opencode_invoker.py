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
from typing import Any, Callable

from logger import get_logger

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


def _get_process_cpu_seconds(pid: int) -> int:
    """Get cumulative CPU seconds for a process via ps. Returns -1 on failure."""
    try:
        result = subprocess.run(
            ["ps", "-o", "time=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=2,
        )
        output = result.stdout.strip()
        if not output:
            return -1
        days = 0
        if "-" in output:
            days_str, output = output.split("-", 1)
            days = int(days_str)
        parts = output.split(":")
        if len(parts) == 3:
            h, m, s = parts
            return days * 86400 + int(h) * 3600 + int(m) * 60 + int(float(s))
        elif len(parts) == 2:
            m, s = parts
            return days * 86400 + int(m) * 60 + int(float(s))
        else:
            return -1
    except Exception:
        return -1


def _format_duration(seconds: int) -> str:
    """Format seconds as compact human-readable duration."""
    if seconds < 60:
        return f"{seconds}s"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h}h{m}m"
    if s:
        return f"{m}m{s}s"
    return f"{m}m"


def start_heartbeat(
    interval_seconds: int,
    model: str,
    mcp_mode: str,
    output_mode: str,
    process: "subprocess.Popen[Any] | None" = None,
    inactivity_timeout: int = 0,
    get_last_activity: Callable[[], float] | None = None,
) -> threading.Thread | None:
    """Monitor an OpenCode subprocess: heartbeat + optional inactivity timeout."""
    if interval_seconds == 0:
        return None

    start_time = time.monotonic()
    last_cpu_time: int = -1
    cpu_stall_start: float | None = None
    killed: bool = False

    if process is not None:
        last_cpu_time = _get_process_cpu_seconds(process.pid)

    def _monitor():
        nonlocal last_cpu_time, cpu_stall_start, killed
        while True:
            threading.Event().wait(interval_seconds)
            if process is not None and process.poll() is not None:
                break

            elapsed = int(time.monotonic() - start_time)
            parts = [f"elapsed={_format_duration(elapsed)}"]

            if process is not None:
                cpu_time = _get_process_cpu_seconds(process.pid)
                if cpu_time >= 0 and last_cpu_time >= 0:
                    cpu_delta = cpu_time - last_cpu_time
                    parts.append(f"cpu=+{cpu_delta}s")

                    if cpu_delta == 0:
                        if cpu_stall_start is None:
                            cpu_stall_start = time.monotonic()
                        stall_dur = int(time.monotonic() - cpu_stall_start)
                        parts.append(f"cpu_stall={_format_duration(stall_dur)}")
                    else:
                        cpu_stall_start = None

                    last_cpu_time = cpu_time

            if get_last_activity is not None:
                since_active = int(time.monotonic() - get_last_activity())
                parts.append(f"active={_format_duration(since_active)}_ago")

            parts.append(f"model={model}")
            parts.append(f"mcp={mcp_mode}")
            parts.append(f"mode={output_mode}")
            parts.append("remaining=unlimited")

            print(
                f"OpenCode still running: {' '.join(parts)}",
                file=sys.stderr,
                flush=True,
            )

            if inactivity_timeout > 0 and cpu_stall_start is not None and process is not None:
                stall_dur = time.monotonic() - cpu_stall_start
                if stall_dur >= inactivity_timeout:
                    print(
                        f"OpenCode inactivity timeout "
                        f"({_format_duration(int(stall_dur))} stall >= {_format_duration(inactivity_timeout)}), "
                        f"sending SIGTERM...",
                        file=sys.stderr,
                        flush=True,
                    )
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    killed = True
                    break

    t = threading.Thread(target=_monitor, daemon=True)
    return t


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
    if "/" not in normalized:
        return f"opencode/{normalized}"
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

    # subagent_mode "off" means no --agent flag (use built-in default behavior)

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
        model=config.model,
        mcp_mode=config.mcp_mode,
        output_mode=config.output_mode,
        process=process,
        inactivity_timeout=config.inactivity_timeout,
        get_last_activity=lambda: last_activity,
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
