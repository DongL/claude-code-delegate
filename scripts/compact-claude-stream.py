#!/usr/bin/env python3
"""Compact Claude Code stream-json into a reviewable final report."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

from profile_logger import append_profile_record, build_profile_record


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


def parse_compact_output(raw_json: str) -> dict[str, Any]:
    """Parse raw Claude Code JSON output into a structured dict.

    Handles both single JSON objects and newline-delimited stream-json.
    Returns result text, usage, cost, model, effort, and other metadata.
    """
    init: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    errors: list[str] = []

    events: list[dict[str, Any]] = []
    try:
        parsed = json.loads(raw_json)
        if isinstance(parsed, dict):
            events.append(parsed)
        elif isinstance(parsed, list):
            events.extend(item for item in parsed if isinstance(item, dict))
    except json.JSONDecodeError:
        for line in raw_json.splitlines():
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

    result_text = (result or {}).get("result") or ""
    usage = (result or {}).get("usage")
    cost_usd = (result or {}).get("total_cost_usd", 0.0)
    terminal_reason = (result or {}).get("terminal_reason") or ""
    is_error = bool((result or {}).get("is_error"))
    cwd = (init or {}).get("cwd") or os.environ.get("CLAUDE_DELEGATE_OBSERVED_CWD")

    return {
        "result": result_text,
        "usage": usage if isinstance(usage, dict) else {},
        "cost_usd": cost_usd if isinstance(cost_usd, (int, float)) else 0.0,
        "terminal_reason": terminal_reason,
        "model": model,
        "effort": effort,
        "permission_mode": permission_mode,
        "mcp_mode": mcp_mode,
        "cwd": cwd,
        "is_error": is_error,
        "has_init": init is not None,
        "has_result": result is not None,
        "errors": errors,
    }


def main() -> int:
    raw = sys.stdin.read()
    parsed = parse_compact_output(raw)

    model = parsed["model"]
    effort = parsed["effort"]
    permission_mode = parsed["permission_mode"]
    mcp_mode = parsed["mcp_mode"]
    result = {
        "result": parsed["result"],
        "usage": parsed["usage"],
        "total_cost_usd": parsed["cost_usd"],
        "terminal_reason": parsed["terminal_reason"],
        "is_error": parsed["is_error"],
    }
    errors: list[str] = list(parsed["errors"])

    if parsed["is_error"] and "error result" not in errors:
        errors.append("error result")

    task_class = os.environ.get("CLAUDE_DELEGATE_OBSERVED_CLASS")
    task_type = os.environ.get("CLAUDE_DELEGATE_OBSERVED_TASK_TYPE")
    context_budget = os.environ.get("CLAUDE_DELEGATE_OBSERVED_CONTEXT_BUDGET")
    prompt_mode = os.environ.get("CLAUDE_DELEGATE_OBSERVED_PROMPT_MODE")
    prompt_template = os.environ.get("CLAUDE_DELEGATE_OBSERVED_PROMPT_TEMPLATE")
    original_prompt_chars = os.environ.get("CLAUDE_DELEGATE_ORIGINAL_PROMPT_CHARS")
    prepared_prompt_chars = os.environ.get("CLAUDE_DELEGATE_PREPARED_PROMPT_CHARS")
    prompt_reduction_pct = os.environ.get("CLAUDE_DELEGATE_PROMPT_REDUCTION_PCT")
    has_init = parsed["has_init"]
    has_result = parsed["has_result"]
    cwd = parsed.get("cwd")

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

    if has_result:
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
        result_dict = result if isinstance(result, dict) else {}
        record = build_profile_record(
            model=model,
            effort=effort,
            permission_mode=permission_mode,
            mcp_mode=mcp_mode,
            task_class=task_class,
            task_type=task_type,
            context_budget=context_budget,
            prompt_mode=prompt_mode,
            prompt_template=prompt_template,
            original_prompt_chars=int(original_prompt_chars or 0),
            prepared_prompt_chars=int(prepared_prompt_chars or 0),
            prompt_reduction_pct=int(prompt_reduction_pct or 0),
            usage=result_dict.get("usage"),
            total_cost_usd=result_dict.get("total_cost_usd"),
            terminal_reason=result_dict.get("terminal_reason"),
            is_error=bool(result_dict.get("is_error")) if result_dict else bool(errors),
        )
        append_profile_record(record, profile_log)

    if errors:
        if has_init or has_result:
            print()
        print("Stream Warnings")
        for error in errors[:5]:
            print(f"- {error}")
        if len(errors) > 5:
            print(f"- ... {len(errors) - 5} more")

    if not has_init and not has_result and not errors:
        return 1
    if has_result and result.get("is_error") is True:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
