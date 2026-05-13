#!/usr/bin/env python3
"""Job manager for async delegation with single-flight lease semantics.

Jobs live under .claude-delegate/runtime/jobs/<job_id>/:
  meta.json   — pid, started_at, model, effort, status
  config.json — persisted InvokerConfig for the detached supervisor
  stdout.txt  — Claude Code stdout (written during execution)
  stderr.txt  — Claude Code stderr (written during execution)
  result.json — returncode, completed_at (written once the process exits)

Single-flight: find_active_lease() returns the first running job whose
PID is still alive.  Callers use this to prevent duplicate delegations.
"""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _get_runtime_root() -> Path:
    return Path(
        os.environ.get(
            "CLAUDE_DELEGATE_RUNTIME_DIR",
            str(Path.cwd() / ".claude-delegate" / "runtime"),
        )
    )


def get_jobs_dir() -> Path:
    jobs_dir = _get_runtime_root() / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    return jobs_dir


def create_job_id() -> str:
    return secrets.token_hex(6)


def _job_dir(job_id: str) -> Path:
    return get_jobs_dir() / job_id


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_job_meta(
    job_id: str,
    pid: int,
    prompt: str,
    model: str,
    effort: str,
    permission_mode: str,
    mcp_mode: str,
    output_mode: str,
) -> dict[str, Any]:
    meta = {
        "job_id": job_id,
        "pid": pid,
        "started_at": _now_iso(),
        "prompt": prompt,
        "model": model,
        "effort": effort,
        "permission_mode": permission_mode,
        "mcp_mode": mcp_mode,
        "output_mode": output_mode,
        "status": "running",
    }
    d = _job_dir(job_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return meta


def read_job_meta(job_id: str) -> dict[str, Any] | None:
    path = _job_dir(job_id) / "meta.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_job_result(job_id: str, returncode: int, stdout: str, stderr: str) -> None:
    d = _job_dir(job_id)
    (d / "stdout.txt").write_text(stdout, encoding="utf-8")
    (d / "stderr.txt").write_text(stderr, encoding="utf-8")
    result = {
        "returncode": returncode,
        "completed_at": _now_iso(),
    }
    (d / "result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_job_result(job_id: str) -> dict[str, Any] | None:
    path = _job_dir(job_id) / "result.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def persist_job_config(job_id: str, config: dict[str, Any]) -> None:
    """Persist InvokerConfig as config.json for the supervisor process."""
    d = _job_dir(job_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.json").write_text(
        json.dumps(config, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_job_config(job_id: str) -> dict[str, Any] | None:
    """Read the persisted InvokerConfig for a job."""
    path = _job_dir(job_id) / "config.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def find_active_lease() -> dict[str, Any] | None:
    """Return meta of the first running job whose PID is alive, or None.

    Jobs whose PID has died while status was "running" are marked
    "abandoned" in-place so subsequent calls skip them quickly.
    """
    jobs_dir = get_jobs_dir()
    if not jobs_dir.exists():
        return None
    for d in sorted(jobs_dir.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        meta = read_job_meta(d.name)
        if meta is None:
            continue
        if meta.get("status") != "running":
            continue
        pid = meta.get("pid")
        if isinstance(pid, int) and _pid_alive(pid):
            return meta
        meta["status"] = "abandoned"
        (d / "meta.json").write_text(
            json.dumps(meta, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return None


def _read_tail(path: Path, max_bytes: int = 2000) -> str:
    try:
        text = path.read_text(encoding="utf-8")
        if len(text) > max_bytes:
            return text[-max_bytes:]
        return text
    except OSError:
        return ""


def get_job_status(job_id: str) -> dict[str, Any]:
    """Return current status of a job.

    Returns a dict with at least {"status": "...", "job_id": "..."}.
    """
    meta = read_job_meta(job_id)
    if meta is None:
        return {"status": "not_found", "job_id": job_id}

    pid = meta.get("pid")
    d = _job_dir(job_id)
    result = read_job_result(job_id)

    if result is not None:
        returncode = result.get("returncode", -1)
        stdout = _read_tail(d / "stdout.txt")
        stderr = _read_tail(d / "stderr.txt")
        if returncode == 0:
            return {
                "status": "completed",
                "job_id": job_id,
                "returncode": 0,
                "stdout": stdout,
                "stderr_tail": stderr[-2000:] if stderr else "",
            }
        else:
            return {
                "status": "failed",
                "job_id": job_id,
                "returncode": returncode,
                "stdout_tail": stdout[-2000:] if stdout else "",
                "stderr_tail": stderr[-2000:] if stderr else "",
            }

    if isinstance(pid, int) and _pid_alive(pid):
        status: dict[str, Any] = {
            "status": "running",
            "job_id": job_id,
            "pid": pid,
            "pid_alive": True,
            "started_at": meta.get("started_at", ""),
        }
        stdout_path = d / "stdout.txt"
        stderr_path = d / "stderr.txt"
        if stdout_path.exists():
            status["stdout_bytes"] = stdout_path.stat().st_size
            status["stdout_tail"] = _read_tail(stdout_path)
        if stderr_path.exists():
            status["stderr_bytes"] = stderr_path.stat().st_size
            status["stderr_tail"] = _read_tail(stderr_path)
        return status

    # PID dead, no result.json — the supervisor did not record a
    # returncode, so we cannot trust the output.  Treat as failed.
    stderr = _read_tail(d / "stderr.txt", max_bytes=10_000)
    return {
        "status": "failed",
        "job_id": job_id,
        "returncode": -1,
        "stdout_tail": _read_tail(d / "stdout.txt", max_bytes=2000),
        "stderr_tail": stderr[-2000:] if stderr else "process exited before waiter recorded result",
    }
