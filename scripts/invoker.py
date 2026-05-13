#!/usr/bin/env python3
"""Invoke Claude Code as a subprocess for delegation."""

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


CLAUDE_ENV_KEYS = (
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
)


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
    inactivity_timeout: int = 0


def load_claude_settings_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Build child env, backfilling Claude Code settings env when sandbox hooks fail."""
    child_env = dict(base_env or os.environ)
    settings_env: dict[str, str] = {}

    for path in (
        Path.home() / ".claude" / "settings.json",
        Path.home() / ".claude" / "settings.local.json",
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
                settings_env[key] = str(value)

    for key, value in settings_env.items():
        child_env.setdefault(key, value)

    return child_env


def isolated_config_enabled(env: dict[str, str] | None = None) -> bool:
    value = (env or os.environ).get("CLAUDE_DELEGATE_ISOLATED_CONFIG", "1")
    return value.lower() not in ("0", "false", "no", "off")


def prepare_isolated_claude_config(child_env: dict[str, str]) -> dict[str, str]:
    """Point Claude Code at a workspace-writable minimal config directory."""
    if not isolated_config_enabled(child_env):
        return child_env

    runtime_root = Path(
        child_env.get(
            "CLAUDE_DELEGATE_RUNTIME_DIR",
            str(Path.cwd() / ".claude-delegate" / "runtime"),
        )
    )
    config_dir = runtime_root / "claude-config"
    config_dir.mkdir(parents=True, exist_ok=True)

    settings_env = {
        key: child_env[key]
        for key in CLAUDE_ENV_KEYS
        if child_env.get(key)
    }
    settings = {"env": settings_env}
    (config_dir / "settings.json").write_text(
        json.dumps(settings, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    updated_env = dict(child_env)
    updated_env["CLAUDE_CONFIG_DIR"] = str(config_dir)
    return updated_env


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


def resolve_mcp_config_path(mcp_mode: str) -> str | None:
    explicit = os.environ.get("CLAUDE_DELEGATE_MCP_CONFIG_PATH")
    if explicit:
        return explicit

    candidates = [
        Path(".mcp.json"),
        Path.home() / ".claude" / "mcp.json",
        Path.home() / ".codex" / "mcp.json",
        Path(__file__).resolve().parents[1] / ".mcp.json",
    ]

    for candidate in candidates:
        try:
            config = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if mcp_mode in (config.get("mcpServers") or {}):
            return str(candidate)
    return None


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
        # Handle days prefix: DD-HH:MM:SS (Linux long-running)
        days = 0
        if "-" in output:
            days_str, output = output.split("-", 1)
            days = int(days_str)
        parts = output.split(":")
        if len(parts) == 3:
            # HH:MM:SS (Linux)
            h, m, s = parts
            return days * 86400 + int(h) * 3600 + int(m) * 60 + int(float(s))
        elif len(parts) == 2:
            # MM:SS.hs (macOS)
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
    effort: str,
    mcp_mode: str,
    output_mode: str,
    process: "subprocess.Popen[Any] | None" = None,
    inactivity_timeout: int = 0,
    get_last_activity: Callable[[], float] | None = None,
) -> threading.Thread | None:
    """Monitor a Claude Code subprocess: heartbeat + optional inactivity timeout.

    Heartbeat format includes elapsed time, CPU delta since last tick, and
    cpu_stall duration when CPU time stops growing.  The orchestrator reads
    stderr and can distinguish "busy reasoning" (cpu=+25s) from "stuck"
    (cpu_stall=8m).

    When *inactivity_timeout* is set and cpu_stall exceeds it the monitor
    sends SIGTERM, waits 5 s, then SIGKILL.
    """
    if interval_seconds == 0:
        return None

    start_time = time.monotonic()
    last_cpu_time: int = -1
    cpu_stall_start: float | None = None
    # Store this thread's reference so the timeout path can signal completion
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
            parts.append(f"effort={effort}")
            parts.append(f"mcp={mcp_mode}")
            parts.append(f"mode={output_mode}")

            print(
                f"Claude Code still running: {' '.join(parts)}",
                file=sys.stderr,
                flush=True,
            )

            # Inactivity timeout — CPU-based for quiet mode
            if inactivity_timeout > 0 and cpu_stall_start is not None and process is not None:
                stall_dur = time.monotonic() - cpu_stall_start
                if stall_dur >= inactivity_timeout:
                    print(
                        f"Claude Code inactivity timeout "
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
        source_path = resolve_mcp_config_path(config.mcp_mode)

    mcp_args, mcp_config_path = generate_mcp_config(config.mcp_mode, source_path)
    child_env = prepare_isolated_claude_config(load_claude_settings_env())
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
        else:
            args.extend(mcp_args)
            args.extend(["--output-format", "json"])

        process = subprocess.Popen(
            [*args, config.prompt],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=child_env,
            text=True,
        )

        # Accumulate stdout in a thread; track last-activity timestamp.
        stdout_lines: list[str] = []
        last_activity = time.monotonic()
        stdout_lock = threading.Lock()

        def _read_stdout():
            nonlocal last_activity
            # process.stdout is not None because we passed stdout=PIPE
            for line in process.stdout:  # type: ignore[union-attr]
                with stdout_lock:
                    stdout_lines.append(line)
                    last_activity = time.monotonic()

        reader = threading.Thread(target=_read_stdout, daemon=True)
        reader.start()

        monitor = start_heartbeat(
            interval_seconds=config.heartbeat_seconds,
            model=config.model,
            effort=config.effort,
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
    finally:
        for f in cleanup_files:
            try:
                Path(f).unlink()
            except OSError:
                pass
