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
from typing import Any

from logger import get_logger
from heartbeat import start_heartbeat

logger = get_logger("invoker")

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
    executor: str = "claude-code"
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
    logger.debug("isolated config prepared", config_dir=str(config_dir))
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
        Path.home() / ".claude" / "mcp.json",
        Path.home() / ".codex" / "mcp.json",
        Path(".mcp.json"),
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


def launch_claude_async(
    config: InvokerConfig,
    stdout_path: str,
    stderr_path: str,
) -> "subprocess.Popen[Any]":
    """Launch the configured executor in the background."""
    if config.executor == "opencode":
        return _launch_opencode_async(config, stdout_path, stderr_path)
    return _launch_claude_code_async(config, stdout_path, stderr_path)


def _launch_opencode_async(
    config: InvokerConfig,
    stdout_path: str,
    stderr_path: str,
) -> "subprocess.Popen[Any]":
    from opencode_invoker import (
        OpenCodeInvokerConfig,
        launch_opencode_async as _launch,
    )

    opencode_config = OpenCodeInvokerConfig(
        model=config.model,
        permission_mode=config.permission_mode,
        mcp_mode=config.mcp_mode,
        subagent_mode=config.subagent_mode,
        heartbeat_seconds=config.heartbeat_seconds,
        output_mode=config.output_mode,
        prompt=config.prompt,
        inactivity_timeout=config.inactivity_timeout,
    )
    return _launch(opencode_config, stdout_path, stderr_path)


def _launch_claude_code_async(
    config: InvokerConfig,
    stdout_path: str,
    stderr_path: str,
) -> "subprocess.Popen[Any]":
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

    mcp_args, _ = generate_mcp_config(config.mcp_mode, source_path)
    child_env = prepare_isolated_claude_config(load_claude_settings_env())

    if config.output_mode == "stream":
        args.extend(mcp_args)
        args.extend(["--verbose", "--output-format", "stream-json", "--include-partial-messages"])
    else:
        args.extend(mcp_args)
        args.extend(["--output-format", "json"])

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


def supervise_job(job_id: str) -> int:
    """Supervise a job: launch Claude Code, wait, then write result.json.

    Reads config.json from the job directory, launches Claude Code via
    launch_claude_async, waits for the process, and records result.json
    with the real returncode.  The meta.json pid is updated once the
    child process starts.
    """
    from job_manager import (
        _job_dir,
        read_job_config,
        read_job_meta,
        write_job_result,
    )

    config_data = read_job_config(job_id)
    if config_data is None:
        logger.error("no config for job", job_id=job_id)
        return 1

    config = InvokerConfig(**config_data)

    job_dir = _job_dir(job_id)
    stdout_path = str(job_dir / "stdout.txt")
    stderr_path = str(job_dir / "stderr.txt")

    process = launch_claude_async(config, stdout_path, stderr_path)

    meta = read_job_meta(job_id)
    if meta:
        meta["pid"] = process.pid
        (job_dir / "meta.json").write_text(
            json.dumps(meta, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    logger.info(
        "supervisor waiting for claude",
        job_id=job_id,
        pid=process.pid,
    )
    process.wait()

    stdout = ""
    stderr = ""
    stdout_file = job_dir / "stdout.txt"
    stderr_file = job_dir / "stderr.txt"
    if stdout_file.exists():
        stdout = stdout_file.read_text(encoding="utf-8")
    if stderr_file.exists():
        stderr = stderr_file.read_text(encoding="utf-8")

    write_job_result(job_id, process.returncode, stdout, stderr)
    logger.info(
        "supervisor recorded result",
        job_id=job_id,
        returncode=process.returncode,
    )

    return process.returncode


def invoke_claude(config: InvokerConfig) -> subprocess.CompletedProcess[Any]:
    if config.executor == "opencode":
        return _invoke_opencode(config)
    return _invoke_claude_code(config)


def _invoke_opencode(config: InvokerConfig) -> subprocess.CompletedProcess[Any]:
    """Route to OpenCode executor."""
    from opencode_invoker import (
        OpenCodeInvokerConfig,
        invoke_opencode as _invoke,
    )

    opencode_config = OpenCodeInvokerConfig(
        model=config.model,
        permission_mode=config.permission_mode,
        mcp_mode=config.mcp_mode,
        subagent_mode=config.subagent_mode,
        heartbeat_seconds=config.heartbeat_seconds,
        output_mode=config.output_mode,
        prompt=config.prompt,
        inactivity_timeout=config.inactivity_timeout,
    )
    return _invoke(opencode_config)


def _invoke_claude_code(config: InvokerConfig) -> subprocess.CompletedProcess[Any]:
    logger.info(
        "starting claude invocation",
        model=config.model,
        effort=config.effort,
        mcp_mode=config.mcp_mode,
    )

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
            stdin=subprocess.DEVNULL,
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
            process=process,
            inactivity_timeout=config.inactivity_timeout,
            get_last_activity=lambda: last_activity,
            extra_fields={
                "model": config.model,
                "effort": config.effort,
                "mcp": config.mcp_mode,
                "mode": config.output_mode,
            },
            prefix="Claude Code",
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
