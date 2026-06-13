#!/usr/bin/env python3
"""MCP server exposing claude-code-delegate tools via stdio."""

from __future__ import annotations

import os
import sys
from typing import Any

_scripts_root = os.path.dirname(os.path.abspath(__file__))
if _scripts_root not in sys.path:
    sys.path.insert(0, _scripts_root)

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("mcp package required: pip install mcp", file=sys.stderr)
    raise SystemExit(1)

from classifier import Classification, classify_prompt, classification_to_dict
import aggregate_profile_log as _agg_mod
import jira_safe_text as _jira_mod

server = FastMCP("claude-code-delegate")


@server.tool(structured_output=False)
async def classify_task(prompt: str) -> dict[str, Any]:
    """Classify a task prompt into task type, recommended model, effort, and permissions."""
    return classification_to_dict(classify_prompt(prompt))


@server.tool(structured_output=False)
async def format_jira_text(markdown: str) -> dict[str, Any]:
    """Convert Markdown text to Jira-safe plain text."""
    return {"plain_text": _jira_mod.markdown_to_plain(markdown)}


@server.tool(structured_output=False)
def delegate_task(
    prompt: str,
    model_tier: str = "auto",
    effort: str = "auto",
    permission_mode: str = "auto",
    mcp_mode: str = "all",
    context_mode: str = "auto",
    allow_subagents: bool = False,
    output_mode: str = "quiet",
    executor: str = "claude-code",
) -> dict[str, Any]:
    """Delegate a task to the selected executor for execution."""
    import importlib

    # Reload pipeline and its key deps to pick up code changes without
    # restarting the MCP server process (long-lived over stdio).
    for mod_name in ("job_manager", "classifier", "invoker", "opencode_invoker", "pipeline"):
        m = sys.modules.get(mod_name)
        if m is not None:
            importlib.reload(m)

    from pipeline import run_delegation_pipeline

    try:
        result = run_delegation_pipeline(
            prompt=prompt,
            model_tier=model_tier,
            effort=effort,
            permission_mode=permission_mode,
            mcp_mode=mcp_mode,
            context_mode=context_mode,
            subagent_mode="on" if allow_subagents else "off",
            output_mode=output_mode,
            executor=executor,
        )
    except Exception as exc:
        return {
            "classification": {},
            "result": "",
            "usage": {},
            "cost_usd": 0.0,
            "terminal_reason": f"pipeline_error: {exc}",
        }

    return {
        "classification": result.classification,
        "result": result.result,
        "usage": result.usage,
        "cost_usd": result.cost_usd,
        "terminal_reason": result.terminal_reason,
        "subagents": getattr(result, "subagents", {}),
    }


@server.tool(structured_output=False)
async def aggregate_profile(
    profile_log_path: str,
    format: str = "text",
) -> dict[str, Any]:
    """Aggregate a CLAUDE_DELEGATE_PROFILE_LOG JSONL file into a summary."""
    records = _agg_mod.load_records(profile_log_path)
    result = _agg_mod.aggregate(records)

    if format == "json":
        return {"result": result}
    else:
        return {"text_summary": _agg_mod.format_text(result)}


@server.tool(structured_output=False)
async def start_delegation(
    prompt: str,
    model_tier: str = "auto",
    effort: str = "auto",
    permission_mode: str = "auto",
    mcp_mode: str = "all",
    context_mode: str = "auto",
    allow_subagents: bool = False,
    output_mode: str = "quiet",
    executor: str = "claude-code",
) -> dict[str, Any]:
    """Start an async delegation job. Returns job_id and status."""
    import importlib

    for mod_name in ("job_manager", "classifier", "invoker", "opencode_invoker", "pipeline"):
        m = sys.modules.get(mod_name)
        if m is not None:
            importlib.reload(m)

    from pipeline import start_delegation_async

    try:
        result = start_delegation_async(
            prompt=prompt,
            model_tier=model_tier,
            effort=effort,
            permission_mode=permission_mode,
            mcp_mode=mcp_mode,
            context_mode=context_mode,
            subagent_mode="on" if allow_subagents else "off",
            output_mode=output_mode,
            executor=executor,
        )
    except Exception as exc:
        return {
            "status": "error",
            "terminal_reason": f"pipeline_error: {exc}",
        }

    return result


@server.tool(structured_output=False)
async def poll_delegation(job_id: str) -> dict[str, Any]:
    """Poll the status of an async delegation job."""
    import importlib

    for mod_name in ("job_manager", "classifier", "invoker", "opencode_invoker", "pipeline"):
        m = sys.modules.get(mod_name)
        if m is not None:
            importlib.reload(m)

    from pipeline import poll_delegation_status

    try:
        result = poll_delegation_status(job_id)
    except Exception as exc:
        return {
            "status": "error",
            "job_id": job_id,
            "terminal_reason": f"pipeline_error: {exc}",
        }

    return result


@server.tool(structured_output=False)
async def poll_delegation_compact(job_id: str) -> dict[str, Any]:
    """Lightweight poll — stat() sizes only, no file tail reads. Saves tokens."""
    import importlib

    for mod_name in ("job_manager",):
        m = sys.modules.get(mod_name)
        if m is not None:
            importlib.reload(m)

    from job_manager import get_job_status_compact

    try:
        result = get_job_status_compact(job_id)
    except Exception as exc:
        return {
            "status": "error",
            "job_id": job_id,
            "terminal_reason": f"pipeline_error: {exc}",
        }

    return result


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
