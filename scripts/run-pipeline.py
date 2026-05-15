#!/usr/bin/env python3
"""Thin CLI wrapper around pipeline.run_delegation_pipeline() for shell invocation.

Also supports --start (async launch with lease) and --poll <job_id> modes.
"""

from __future__ import annotations

import json
import os
import sys


def _print_usage() -> None:
    print(
        "Usage: run-pipeline.py <prompt> <output_mode> <model_tier> <effort> "
        "<permission_mode> <mcp_mode> <context_mode> <subagent_mode> <executor>",
        file=sys.stderr,
    )
    print(
        "       run-pipeline.py --start <prompt> <output_mode> <model_tier> <effort> "
        "<permission_mode> <mcp_mode> <context_mode> <subagent_mode> <executor>",
        file=sys.stderr,
    )
    print(
        "       run-pipeline.py --poll <job_id>",
        file=sys.stderr,
    )


def main() -> int:
    if len(sys.argv) < 2:
        _print_usage()
        return 2

    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, scripts_dir)

    if sys.argv[1] == "--start":
        return _handle_start()
    elif sys.argv[1] == "--poll":
        return _handle_poll()
    elif sys.argv[1] == "--supervise":
        return _handle_supervise()
    else:
        return _handle_exec()


def _handle_start() -> int:
    from pipeline import start_delegation_async

    if len(sys.argv) < 3:
        print("Missing prompt for --start", file=sys.stderr)
        return 2

    prompt = sys.argv[2]
    output_mode = sys.argv[3] if len(sys.argv) > 3 else "quiet"
    model_tier = sys.argv[4] if len(sys.argv) > 4 else "auto"
    effort = sys.argv[5] if len(sys.argv) > 5 else "auto"
    permission_mode = sys.argv[6] if len(sys.argv) > 6 else "auto"
    mcp_mode = sys.argv[7] if len(sys.argv) > 7 else "all"
    context_mode = sys.argv[8] if len(sys.argv) > 8 else "auto"
    subagent_mode = sys.argv[9] if len(sys.argv) > 9 else "off"
    executor = sys.argv[10] if len(sys.argv) > 10 else "claude-code"

    result = start_delegation_async(
        prompt=prompt,
        model_tier=model_tier,
        effort=effort,
        permission_mode=permission_mode,
        mcp_mode=mcp_mode,
        context_mode=context_mode,
        subagent_mode=subagent_mode,
        output_mode=output_mode,
        executor=executor,
    )

    print(json.dumps(result, ensure_ascii=False))
    # Exit 0 for running and lease_held; the caller uses the JSON status field
    return 0


def _handle_poll() -> int:
    from pipeline import poll_delegation_status

    if len(sys.argv) < 3 or not sys.argv[2]:
        print("Missing job_id for --poll", file=sys.stderr)
        return 2

    job_id = sys.argv[2]
    result = poll_delegation_status(job_id)

    print(json.dumps(result, ensure_ascii=False))
    if result.get("status") == "not_found":
        return 1
    return 0


def _handle_supervise() -> int:
    """Internal: supervise a job to completion and write result.json."""
    from invoker import supervise_job

    if len(sys.argv) < 3 or not sys.argv[2]:
        print("Missing job_id for --supervise", file=sys.stderr)
        return 2

    job_id = sys.argv[2]
    rc = supervise_job(job_id)
    return rc


def _handle_exec() -> int:
    from pipeline import run_delegation_pipeline

    if len(sys.argv) < 3:
        _print_usage()
        return 2

    prompt = sys.argv[1]
    output_mode = sys.argv[2]
    model_tier = sys.argv[3] if len(sys.argv) > 3 else "auto"
    effort = sys.argv[4] if len(sys.argv) > 4 else "auto"
    permission_mode = sys.argv[5] if len(sys.argv) > 5 else "auto"
    mcp_mode = sys.argv[6] if len(sys.argv) > 6 else "all"
    context_mode = sys.argv[7] if len(sys.argv) > 7 else "auto"
    subagent_mode = sys.argv[8] if len(sys.argv) > 8 else "off"
    executor = sys.argv[9] if len(sys.argv) > 9 else "claude-code"

    result = run_delegation_pipeline(
        prompt=prompt,
        model_tier=model_tier,
        effort=effort,
        permission_mode=permission_mode,
        mcp_mode=mcp_mode,
        context_mode=context_mode,
        subagent_mode=subagent_mode,
        output_mode=output_mode,
        executor=executor,
    )

    # Print compact report (same format as compact-claude-stream.py main())
    executor_name = os.environ.get("CLAUDE_DELEGATE_EXECUTOR_NAME", "Claude Code")
    if result.model or result.effort or result.permission_mode or result.mcp_mode:
        print(executor_name)
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
