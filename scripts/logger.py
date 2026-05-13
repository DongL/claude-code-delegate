#!/usr/bin/env python3
"""Structured logging for claude-code-delegate.

Output goes to stderr.  Format and level controlled by env vars:
  CLAUDE_DELEGATE_LOG_LEVEL  — DEBUG | INFO | WARN | ERROR (default INFO)
  CLAUDE_DELEGATE_LOG_FORMAT — json | text (default json)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

_LEVELS: dict[str, int] = {
    "DEBUG": 10,
    "INFO": 20,
    "WARN": 30,
    "ERROR": 40,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
            print(json.dumps(record, ensure_ascii=False), file=sys.stderr, flush=True)
        else:
            parts = [f"{k}={v}" for k, v in kwargs.items()]
            suffix = " " + " ".join(parts) if parts else ""
            print(
                f"{_now_iso()} [{level}] {self.name}: {msg}{suffix}",
                file=sys.stderr,
                flush=True,
            )

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
