#!/usr/bin/env python3
"""Shared heartbeat monitor for subprocess invokers."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from typing import Any, Callable


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
    process: "subprocess.Popen[Any] | None" = None,
    inactivity_timeout: int = 0,
    get_last_activity: Callable[[], float] | None = None,
    extra_fields: dict[str, str] | None = None,
    prefix: str = "Process",
) -> threading.Thread | None:
    """Monitor a subprocess: heartbeat + optional inactivity timeout.

    *prefix* is the label printed before "still running:".
    *extra_fields* are key=value pairs appended to each heartbeat line.
    """
    if interval_seconds == 0:
        return None

    start_time = time.monotonic()
    last_cpu_time: int = -1
    cpu_stall_start: float | None = None

    if process is not None:
        last_cpu_time = _get_process_cpu_seconds(process.pid)

    def _monitor():
        nonlocal last_cpu_time, cpu_stall_start
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

            if extra_fields:
                for k, v in extra_fields.items():
                    parts.append(f"{k}={v}")

            parts.append("remaining=unlimited")

            print(
                f"{prefix} still running: {' '.join(parts)}",
                file=sys.stderr,
                flush=True,
            )

            if inactivity_timeout > 0 and cpu_stall_start is not None and process is not None:
                stall_dur = time.monotonic() - cpu_stall_start
                if stall_dur >= inactivity_timeout:
                    print(
                        f"{prefix} inactivity timeout "
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
                    break

    t = threading.Thread(target=_monitor, daemon=True)
    return t
