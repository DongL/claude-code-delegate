"""Audit log for delegation attempts with stable contract."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def write_audit_record(
    *,
    delegation_id: str = "",
    executor: str = "",
    model: str = "",
    duration_ms: int = 0,
    exit_code: int = 0,
    error_message: str = "",
    cost: float = 0.0,
    release_gate: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "delegation_id": delegation_id,
        "executor": executor,
        "model": model,
        "duration_ms": duration_ms,
        "exit_code": exit_code,
        "error_message": error_message,
        "cost": cost,
        "release_gate": release_gate,
    }
    if extra:
        record["extra"] = extra

    audit_path = os.environ.get("CLAUDE_DELEGATE_AUDIT_LOG")
    if audit_path:
        try:
            path = Path(audit_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        except OSError:
            pass

    return record


def load_audit_records(audit_path: str) -> list[dict[str, Any]]:
    path = Path(audit_path)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records
