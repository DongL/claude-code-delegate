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

from classifier import Classification, classify_prompt

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
_aggregate_mod = None
_jira_safe_mod = None


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
    from pipeline import run_delegation_pipeline

    result = run_delegation_pipeline(
        prompt=prompt,
        model_tier=model_tier,
        effort=effort,
        permission_mode=permission_mode,
        mcp_mode=mcp_mode,
        context_mode=context_mode,
        subagent_mode="on" if allow_subagents else "off",
        output_mode=output_mode,
    )

    return {
        "classification": result.classification,
        "result": result.result,
        "usage": result.usage,
        "cost_usd": result.cost_usd,
        "terminal_reason": result.terminal_reason,
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
