#!/usr/bin/env python3
"""Profile record logger for Claude Code delegation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_profile_record(
    *,
    model: str | None = None,
    effort: str | None = None,
    permission_mode: str | None = None,
    mcp_mode: str | None = None,
    task_class: str | None = None,
    task_type: str | None = None,
    context_budget: str | None = None,
    prompt_mode: str | None = None,
    prompt_template: str | None = None,
    original_prompt_chars: int = 0,
    prepared_prompt_chars: int = 0,
    prompt_reduction_pct: int = 0,
    usage: dict[str, Any] | None = None,
    total_cost_usd: float | None = None,
    terminal_reason: str | None = None,
    is_error: bool = False,
) -> dict[str, Any]:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "effort": effort,
        "permissionMode": permission_mode,
        "mcpMode": mcp_mode,
        "class": task_class,
        "taskType": task_type,
        "contextBudget": context_budget,
        "promptMode": prompt_mode,
        "promptTemplate": prompt_template,
        "originalPromptChars": original_prompt_chars,
        "preparedPromptChars": prepared_prompt_chars,
        "promptReductionPct": prompt_reduction_pct,
        "usage": usage if isinstance(usage, dict) else {},
        "totalCostUsd": total_cost_usd,
        "terminalReason": terminal_reason,
        "isError": is_error,
    }


def append_profile_record(record: dict, profile_log_path: str) -> None:
    if not profile_log_path:
        return
    path = Path(profile_log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
