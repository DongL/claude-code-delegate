#!/usr/bin/env python3
"""Thin CLI wrapper around pipeline.run_delegation_pipeline() for shell invocation."""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    if len(sys.argv) < 3:
        print(
            "Usage: run-pipeline.py <prompt> <output_mode> <model_tier> <effort> "
            "<permission_mode> <mcp_mode> <context_mode> <subagent_mode>",
            file=sys.stderr,
        )
        return 2

    prompt = sys.argv[1]
    output_mode = sys.argv[2]
    model_tier = sys.argv[3] if len(sys.argv) > 3 else "auto"
    effort = sys.argv[4] if len(sys.argv) > 4 else "auto"
    permission_mode = sys.argv[5] if len(sys.argv) > 5 else "auto"
    mcp_mode = sys.argv[6] if len(sys.argv) > 6 else "all"
    context_mode = sys.argv[7] if len(sys.argv) > 7 else "auto"
    subagent_mode = sys.argv[8] if len(sys.argv) > 8 else "off"

    # Ensure scripts dir is on path for imports
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, scripts_dir)

    from pipeline import run_delegation_pipeline

    result = run_delegation_pipeline(
        prompt=prompt,
        model_tier=model_tier,
        effort=effort,
        permission_mode=permission_mode,
        mcp_mode=mcp_mode,
        context_mode=context_mode,
        subagent_mode=subagent_mode,
        output_mode=output_mode,
    )

    # Print compact report (same format as compact-claude-stream.py main())
    if result.model or result.effort or result.permission_mode or result.mcp_mode:
        print("Claude Code")
        if result.model:
            print(f"- model: {result.model}")
        if result.effort:
            print(f"- effort: {result.effort}")
        if result.permission_mode:
            print(f"- permissionMode: {result.permission_mode}")
        if result.mcp_mode:
            print(f"- mcpMode: {result.mcp_mode}")
        print()

    class_name = result.classification.get("name", "")
    if class_name or result.task_type or result.context_budget:
        print("Classification")
        if class_name:
            print(f"- class: {class_name}")
        if result.task_type:
            print(f"- taskType: {result.task_type}")
        if result.context_budget:
            print(f"- contextBudget: {result.context_budget}")
        print()

    if result.prompt_mode or result.prompt_template or result.original_prompt_chars or result.prepared_prompt_chars:
        print("Prompt")
        if result.prompt_mode:
            print(f"- mode: {result.prompt_mode}")
        if result.prompt_template:
            print(f"- template: {result.prompt_template}")
        if result.original_prompt_chars or result.prepared_prompt_chars:
            print(f"- originalChars: {result.original_prompt_chars}, preparedChars: {result.prepared_prompt_chars}")
        print()

    print("Result")
    print(result.result)

    usage = result.usage
    if isinstance(usage, dict) and usage:
        print()
        print("Usage")
        parts = []
        for key in ("input_tokens", "cache_read_input_tokens", "output_tokens"):
            val = usage.get(key)
            if isinstance(val, int):
                parts.append(f"{key}={val}")
        input_tokens = usage.get("input_tokens")
        cache_read = usage.get("cache_read_input_tokens")
        if isinstance(input_tokens, int) and isinstance(cache_read, int):
            denom = input_tokens + cache_read
            if denom:
                parts.append(f"cache_hit_ratio={cache_read / denom:.2f}")
        print(f"- {', '.join(parts)}")

        if isinstance(result.cost_usd, (int, float)):
            print(f"- total_cost_usd={result.cost_usd:.6f}")

        if result.terminal_reason:
            print(f"- terminal_reason={result.terminal_reason}")

    return 1 if result.is_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
