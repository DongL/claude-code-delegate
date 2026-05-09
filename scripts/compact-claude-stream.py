#!/usr/bin/env python3
"""Compact Claude Code stream-json into a reviewable final report."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _fmt_usage(usage: dict[str, Any]) -> str:
    parts = []
    for key in ("input_tokens", "cache_read_input_tokens", "output_tokens"):
        value = usage.get(key)
        if isinstance(value, int):
            parts.append(f"{key}={value}")
    input_tokens = usage.get("input_tokens")
    cache_read = usage.get("cache_read_input_tokens")
    if isinstance(input_tokens, int) and isinstance(cache_read, int):
        denominator = input_tokens + cache_read
        if denominator:
            parts.append(f"cache_hit_ratio={cache_read / denominator:.2f}")
    return ", ".join(parts)


def main() -> int:
    init: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    errors: list[str] = []
    raw = sys.stdin.read()

    events: list[dict[str, Any]] = []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            events.append(parsed)
        elif isinstance(parsed, list):
            events.extend(item for item in parsed if isinstance(item, dict))
    except json.JSONDecodeError:
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                errors.append(line[:500])
                continue
            if isinstance(event, dict):
                events.append(event)

    for event in events:
        event_type = event.get("type")
        if event_type == "system" and event.get("subtype") == "init":
            init = event
        elif event_type == "result":
            result = event
        elif "result" in event or "usage" in event:
            result = event
        elif event.get("is_error") is True:
            errors.append(json.dumps(event, ensure_ascii=False)[:1000])

    model = (init or {}).get("model") or os.environ.get("CLAUDE_DELEGATE_OBSERVED_MODEL")
    effort = (init or {}).get("effort") or os.environ.get("CLAUDE_DELEGATE_OBSERVED_EFFORT")
    permission_mode = (init or {}).get("permissionMode") or os.environ.get(
        "CLAUDE_DELEGATE_OBSERVED_PERMISSION_MODE"
    )
    mcp_mode = (init or {}).get("mcpMode") or os.environ.get(
        "CLAUDE_DELEGATE_OBSERVED_MCP_MODE"
    )
    task_class = os.environ.get("CLAUDE_DELEGATE_OBSERVED_CLASS")
    task_type = os.environ.get("CLAUDE_DELEGATE_OBSERVED_TASK_TYPE")
    context_budget = os.environ.get("CLAUDE_DELEGATE_OBSERVED_CONTEXT_BUDGET")
    prompt_mode = os.environ.get("CLAUDE_DELEGATE_OBSERVED_PROMPT_MODE")
    prompt_template = os.environ.get("CLAUDE_DELEGATE_OBSERVED_PROMPT_TEMPLATE")
    original_prompt_chars = os.environ.get("CLAUDE_DELEGATE_ORIGINAL_PROMPT_CHARS")
    prepared_prompt_chars = os.environ.get("CLAUDE_DELEGATE_PREPARED_PROMPT_CHARS")
    prompt_reduction_pct = os.environ.get("CLAUDE_DELEGATE_PROMPT_REDUCTION_PCT")
    cwd = (init or {}).get("cwd") or os.environ.get("CLAUDE_DELEGATE_OBSERVED_CWD")

    has_profile = any(
        (
            task_class,
            task_type,
            context_budget,
            prompt_mode,
            prompt_template,
            original_prompt_chars,
            prepared_prompt_chars,
        )
    )

    if model or effort or permission_mode or mcp_mode or has_profile or cwd:
        print("Claude Code")
        if model:
            print(f"- model: {model}")
        if effort:
            print(f"- effort: {effort}")
        if permission_mode:
            print(f"- permissionMode: {permission_mode}")
        if mcp_mode:
            print(f"- mcpMode: {mcp_mode}")
        if task_class:
            print(f"- class: {task_class}")
        if task_type:
            print(f"- taskType: {task_type}")
        if context_budget:
            print(f"- contextBudget: {context_budget}")
        if prompt_mode:
            print(f"- promptMode: {prompt_mode}")
        if prompt_template:
            print(f"- promptTemplate: {prompt_template}")
        if original_prompt_chars and prepared_prompt_chars:
            print(
                "- promptChars: "
                f"original={original_prompt_chars}, prepared={prepared_prompt_chars}, "
                f"reduction_pct={prompt_reduction_pct or '0'}"
            )
        if cwd:
            print(f"- cwd: {cwd}")

    if result:
        if model or effort or permission_mode or mcp_mode or has_profile or cwd:
            print()
        print("Result")
        print(result.get("result") or "")

        usage = result.get("usage")
        if isinstance(usage, dict):
            usage_text = _fmt_usage(usage)
            if usage_text:
                print()
                print("Usage")
                print(f"- {usage_text}")

        cost = result.get("total_cost_usd")
        if isinstance(cost, (int, float)):
            print(f"- total_cost_usd={cost:.6f}")

        terminal_reason = result.get("terminal_reason")
        if terminal_reason:
            print(f"- terminal_reason={terminal_reason}")

    profile_log = os.environ.get("CLAUDE_DELEGATE_PROFILE_LOG")
    if profile_log:
        usage = result.get("usage") if isinstance(result, dict) else None
        record = {
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
            "originalPromptChars": int(original_prompt_chars or 0),
            "preparedPromptChars": int(prepared_prompt_chars or 0),
            "promptReductionPct": int(prompt_reduction_pct or 0),
            "usage": usage if isinstance(usage, dict) else {},
            "totalCostUsd": result.get("total_cost_usd") if isinstance(result, dict) else None,
            "terminalReason": result.get("terminal_reason") if isinstance(result, dict) else None,
            "isError": bool(result.get("is_error")) if isinstance(result, dict) else bool(errors),
        }
        path = Path(profile_log)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    if errors:
        if init or result:
            print()
        print("Stream Warnings")
        for error in errors[:5]:
            print(f"- {error}")
        if len(errors) > 5:
            print(f"- ... {len(errors) - 5} more")

    if not init and not result and not errors:
        return 1
    if result and result.get("is_error") is True:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
