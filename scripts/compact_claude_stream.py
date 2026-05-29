#!/usr/bin/env python3
"""Compact Claude Code stream-json into a reviewable final report.

Delegates parsing to per-backend adapters:
- claude_adapter: Claude Code stream-json (init/result events)
- opencode_adapter: OpenCode event stream (text/step_finish/error events)
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from claude_adapter import parse_claude_events, _deserialize as _claude_deserialize
from opencode_adapter import parse_opencode_events, _deserialize as _opencode_deserialize


def _fmt_usage(usage: dict[str, Any]) -> str:
    parts = []
    for key in ("input_tokens", "cache_read_input_tokens", "output_tokens", "thinking_tokens"):
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


def _is_opencode_format(events: list[dict[str, Any]]) -> bool:
    """Detect OpenCode format by presence of text/step_finish/error event types."""
    opencode_types = {"text", "step_finish", "error"}
    return any(e.get("type") in opencode_types for e in events)


def parse_compact_output(raw_json: str) -> dict[str, Any]:
    """Parse raw JSON output into a structured dict.

    Detects the backend format and delegates to the appropriate adapter:
    - Claude Code: single JSON or newline-delimited stream-json.
    - OpenCode: event stream with text, step_finish, and error events.
    Returns result text, usage, cost, model, effort, and other metadata.
    """
    claude_events = _claude_deserialize(raw_json)
    opencode_events = _opencode_deserialize(raw_json)

    if _is_opencode_format(opencode_events):
        result = parse_opencode_events(opencode_events)
    else:
        result = parse_claude_events(claude_events)
        # Merge any deserialization errors from the Claude path
        if not result.get("errors"):
            raw_errors: list[str] = []
            try:
                json.loads(raw_json)
            except json.JSONDecodeError:
                for line in raw_json.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        json.loads(line)
                    except json.JSONDecodeError:
                        raw_errors.append(line[:500])
            result["errors"] = raw_errors

    return result


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

    subagent_mode = os.environ.get("CLAUDE_DELEGATE_OBSERVED_SUBAGENT_MODE")
    subagent_count = os.environ.get("CLAUDE_DELEGATE_OBSERVED_SUBAGENT_COUNT")

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

    executor_name = os.environ.get("CLAUDE_DELEGATE_EXECUTOR_NAME", "Claude Code")

    has_metadata = bool(model or effort or permission_mode or mcp_mode or has_profile or cwd)

    if has_metadata or subagent_mode:
        if has_metadata:
            print(executor_name)
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

        if subagent_mode:
            if has_metadata:
                print()
            print("Subagents")
            allowed = subagent_mode == "on"
            print(f"- mode: {subagent_mode}")
            print(f"- allowed: {str(allowed).lower()}")
            if subagent_count is not None:
                print(f"- observedCount: {subagent_count}")
            else:
                print(f"- observedCount: unknown")
            if not allowed:
                print(f"- observedSource: disabled")
            elif subagent_count is not None:
                print(f"- observedSource: stream_events")
            else:
                print(f"- observedSource: not_observable_in_quiet_json")

    if has_result:
        if has_metadata or subagent_mode:
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
