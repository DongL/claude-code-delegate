#!/usr/bin/env python3
"""MCP server exposing claude-code-delegate tools via stdio."""

from __future__ import annotations

import importlib.util
import os
import sys
import threading
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("mcp package required: pip install mcp", file=sys.stderr)
    raise SystemExit(1)

from classifier import Classification, classify_prompt, FLASH_MODEL, PRO_MODEL
from envelope_builder import build_prepared_prompt
from invoker import InvokerConfig, invoke_claude, start_heartbeat

server = FastMCP("claude-code-delegate")


def _import_script(name: str):
    """Import a script by filename from the same directory (handles hyphens in name)."""
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"),
        os.path.join(scripts_dir, f"{name}.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Imported lazily by tools that need them
_compact_mod = None
_aggregate_mod = None
_jira_safe_mod = None


def _get_compact():
    global _compact_mod
    if _compact_mod is None:
        _compact_mod = _import_script("compact-claude-stream")
    return _compact_mod


def _get_aggregate():
    global _aggregate_mod
    if _aggregate_mod is None:
        _aggregate_mod = _import_script("aggregate-profile-log")
    return _aggregate_mod


def _get_jira_safe():
    global _jira_safe_mod
    if _jira_safe_mod is None:
        _jira_safe_mod = _import_script("jira-safe-text")
    return _jira_safe_mod


def _classification_to_dict(c: Classification) -> dict[str, Any]:
    return {
        "name": c.name,
        "task_type": c.task_type,
        "model": c.model,
        "effort": c.effort,
        "permission_mode": c.permission_mode,
        "context_budget": c.context_budget,
        "use_template": c.use_template,
    }


def _pick_model(model_tier: str) -> str:
    env_model = os.environ.get("CLAUDE_DELEGATE_MODEL")
    if env_model:
        return env_model
    return FLASH_MODEL if model_tier == "flash" else PRO_MODEL


def _resolve_auto(value: str, fallback: str) -> str:
    return value if value != "auto" else fallback


@server.tool()
async def classify_task(prompt: str) -> dict[str, Any]:
    """Classify a task prompt into task type, recommended model, effort, and permissions."""
    classification = classify_prompt(prompt)
    return _classification_to_dict(classification)


@server.tool()
async def format_jira_text(markdown: str) -> dict[str, Any]:
    """Convert Markdown text to Jira-safe plain text."""
    jira_safe = _get_jira_safe()
    return {"plain_text": jira_safe.markdown_to_plain(markdown)}


@server.tool()
async def delegate_task(
    prompt: str,
    model_tier: str = "auto",
    effort: str = "auto",
    permission_mode: str = "auto",
    mcp_mode: str = "all",
    context_mode: str = "auto",
    allow_subagents: bool = False,
    output_mode: str = "quiet",
) -> dict[str, Any]:
    """Delegate a task to Claude Code for execution.

    Classifies the prompt, builds a prepared prompt, invokes Claude Code,
    parses the output, and optionally logs a profile record.
    """
    # 1. Classification
    classification = classify_prompt(prompt)

    # Resolve explicit args with env-var override
    resolved_model_tier = model_tier
    resolved_effort = os.environ.get("CLAUDE_DELEGATE_EFFORT") or effort
    resolved_permission = (
        os.environ.get("CLAUDE_DELEGATE_PERMISSION_MODE") or permission_mode
    )
    resolved_mcp = os.environ.get("CLAUDE_DELEGATE_MCP_MODE") or mcp_mode
    resolved_context = os.environ.get("CLAUDE_DELEGATE_CONTEXT_MODE") or context_mode
    resolved_subagents = (
        "on"
        if os.environ.get("CLAUDE_DELEGATE_SUBAGENTS", "").lower() == "on"
        or allow_subagents
        else "off"
    )

    model = _pick_model(resolved_model_tier) if resolved_model_tier != "auto" else classification.model
    final_effort = _resolve_auto(resolved_effort, classification.effort)
    final_permission = _resolve_auto(resolved_permission, classification.permission_mode)
    final_context = resolved_context

    # 2. Build prepared prompt
    final_prompt, _mode = build_prepared_prompt(prompt, classification, final_context)

    # 3. Build InvokerConfig
    heartbeat_seconds = 30
    try:
        heartbeat_seconds = int(os.environ.get("CLAUDE_DELEGATE_HEARTBEAT_SECONDS", "30"))
    except (ValueError, TypeError):
        pass

    config = InvokerConfig(
        model=model,
        effort=final_effort,
        permission_mode=final_permission,
        mcp_mode=resolved_mcp,
        subagent_mode=resolved_subagents,
        heartbeat_seconds=heartbeat_seconds,
        output_mode=output_mode,
        prompt=final_prompt,
    )

    # 4. Start heartbeat
    heartbeat = start_heartbeat(
        config.heartbeat_seconds, model, final_effort, resolved_mcp, output_mode
    )
    if heartbeat:
        heartbeat.start()

    try:
        # 5. Invoke Claude Code
        result = invoke_claude(config)

        # 6. Parse output
        if output_mode == "stream":
            parsed = {
                "result": result.stdout,
                "usage": {},
                "cost_usd": 0.0,
                "terminal_reason": "",
                "is_error": result.returncode != 0,
            }
        else:
            compact = _get_compact()
            parsed = compact.parse_compact_output(result.stdout)
    finally:
        pass  # daemon thread cleans up automatically

    # 7. Profile logging
    profile_log = os.environ.get("CLAUDE_DELEGATE_PROFILE_LOG")
    if profile_log:
        from profile_logger import append_profile_record
        from datetime import datetime, timezone

        usage = parsed.get("usage")
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "effort": final_effort,
            "isError": bool(parsed.get("is_error")),
            "usage": usage if isinstance(usage, dict) else {},
        }
        append_profile_record(record, profile_log)

    return {
        "classification": _classification_to_dict(classification),
        "result": parsed.get("result", ""),
        "usage": parsed.get("usage", {}),
        "cost_usd": parsed.get("cost_usd", 0.0),
        "terminal_reason": parsed.get("terminal_reason", ""),
    }


@server.tool()
async def aggregate_profile(
    profile_log_path: str,
    format: str = "text",
) -> dict[str, Any]:
    """Aggregate a CLAUDE_DELEGATE_PROFILE_LOG JSONL file into a summary.

    Supports 'text' and 'json' output formats.
    """
    agg = _get_aggregate()
    records = agg.load_records(profile_log_path)
    result = agg.aggregate(records)

    if format == "json":
        return {"result": result}
    else:
        return {"text_summary": agg.format_text(result)}


if __name__ == "__main__":
    server.run()
