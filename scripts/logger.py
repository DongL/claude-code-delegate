#!/usr/bin/env python3
"""Structured logging for claude-code-delegate.

Output goes to stderr.  Format and level controlled by env vars:
  CLAUDE_DELEGATE_LOG_LEVEL  — DEBUG | INFO | WARN | ERROR (default INFO)
  CLAUDE_DELEGATE_LOG_FORMAT — json | text (default json)
  CLAUDE_DELEGATE_LOG_FILE   — path to log file (stderr-only when unset)
  CLAUDE_DELEGATE_LOG_FILE_MAX_BYTES — max bytes before rename to .1 (default 1_048_576)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_LEVELS: dict[str, int] = {
    "DEBUG": 10,
    "INFO": 20,
    "WARN": 30,
    "ERROR": 40,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_log_file: Path | None = None
_log_file_max_bytes: int = 1_048_576


def _resolve_log_file() -> Path | None:
    path = os.environ.get("CLAUDE_DELEGATE_LOG_FILE")
    if not path:
        return None
    return Path(path)


def _resolve_log_file_max_bytes() -> int:
    try:
        return int(
            os.environ.get("CLAUDE_DELEGATE_LOG_FILE_MAX_BYTES", "1048576")
        )
    except (ValueError, TypeError):
        return 1_048_576


def _write_to_file(line: str) -> None:
    global _log_file, _log_file_max_bytes
    if _log_file is None:
        resolved = _resolve_log_file()
        _log_file_max_bytes = _resolve_log_file_max_bytes()
        if resolved is None:
            return
        _log_file = resolved
    try:
        _log_file.parent.mkdir(parents=True, exist_ok=True)
        if _log_file.exists() and _log_file.stat().st_size >= _log_file_max_bytes:
            backup = _log_file.with_suffix(_log_file.suffix + ".1")
            backup.unlink(missing_ok=True)
            _log_file.rename(backup)
        with _log_file.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


class Logger:
    def __init__(self, name: str, level: int, fmt: str) -> None:
        self.name = name
        self.level = level
        self.fmt = fmt

    def _emit(self, level: str, msg: str, **kwargs: object) -> None:
        if _LEVELS[level] < self.level:
            return
        if self.fmt == "json":
            record: dict[str, object] = {
                "ts": _now_iso(),
                "level": level,
                "logger": self.name,
                "msg": msg,
            }
            record.update(kwargs)
            line = json.dumps(record, ensure_ascii=False)
            print(line, file=sys.stderr, flush=True)
            _write_to_file(line)
        else:
            parts = [f"{k}={v}" for k, v in kwargs.items()]
            suffix = " " + " ".join(parts) if parts else ""
            line = f"{_now_iso()} [{level}] {self.name}: {msg}{suffix}"
            print(line, file=sys.stderr, flush=True)
            _write_to_file(line)

    def debug(self, msg: str, **kwargs: object) -> None:
        self._emit("DEBUG", msg, **kwargs)

    def info(self, msg: str, **kwargs: object) -> None:
        self._emit("INFO", msg, **kwargs)

    def warn(self, msg: str, **kwargs: object) -> None:
        self._emit("WARN", msg, **kwargs)

    def error(self, msg: str, **kwargs: object) -> None:
        self._emit("ERROR", msg, **kwargs)


def get_logger(name: str) -> Logger:
    level = os.environ.get("CLAUDE_DELEGATE_LOG_LEVEL", "INFO").upper()
    if level not in _LEVELS:
        level = "INFO"
    fmt = os.environ.get("CLAUDE_DELEGATE_LOG_FORMAT", "json").lower()
    if fmt not in ("json", "text"):
        fmt = "json"
    return Logger(name=name, level=_LEVELS[level], fmt=fmt)
