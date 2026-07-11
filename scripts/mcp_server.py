#!/usr/bin/env python3
"""MCP server exposing claude-code-delegate tools via stdio."""

from __future__ import annotations

import os
import sys
from pathlib import Path
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


# --------------------------------------------------------------------------
# Change-contract tools (docs/prd/change-contracts.md section 19)
# --------------------------------------------------------------------------


@server.tool(structured_output=False)
async def create_change_spec(
    spec: dict[str, Any],
    project_root: str | None = None,
) -> dict[str, Any]:
    """Validate and persist an orchestrator-authored change contract."""
    import importlib

    for mod_name in ("change_spec", "pipeline"):
        m = sys.modules.get(mod_name)
        if m is not None:
            importlib.reload(m)

    from change_spec import change_spec_from_dict, save_change_spec, validate_change_spec

    try:
        resolved_root = Path(project_root) if project_root else Path.cwd()
        parsed = change_spec_from_dict(spec)
        validate_change_spec(parsed)
        path = save_change_spec(resolved_root, parsed)
    except Exception as exc:
        return {"error": str(exc)}

    return {
        "change_id": parsed.change_id,
        "path": str(path),
        "status": parsed.status,
        "task_count": len(parsed.tasks),
        "requirement_count": len(parsed.requirements),
    }


@server.tool(structured_output=False)
async def get_change_spec(
    change_id: str,
    project_root: str | None = None,
) -> dict[str, Any]:
    """Inspect a change contract: goal, status, task statuses/blockers, latest run."""
    import importlib

    for mod_name in ("change_spec", "pipeline"):
        m = sys.modules.get(mod_name)
        if m is not None:
            importlib.reload(m)

    from change_spec import get_latest_run_record, get_task_readiness, load_change_spec

    try:
        resolved_root = Path(project_root) if project_root else Path.cwd()
        spec = load_change_spec(resolved_root, change_id)

        tasks = []
        for task in spec.tasks:
            ready, blockers = get_task_readiness(spec, task.id)
            tasks.append(
                {
                    "id": task.id,
                    "title": task.title,
                    "status": task.status,
                    "ready": ready,
                    "blockers": blockers,
                }
            )

        latest_run = get_latest_run_record(resolved_root, change_id)
    except Exception as exc:
        return {"error": str(exc)}

    return {
        "change_id": spec.change_id,
        "title": spec.title,
        "status": spec.status,
        "goal": spec.goal,
        "tasks": tasks,
        "latest_run": latest_run,
    }


@server.tool(structured_output=False)
async def delegate_change_task(
    change_id: str,
    task_id: str,
    project_root: str | None = None,
    correction: str | None = None,
    model_tier: str = "auto",
    effort: str = "auto",
    permission_mode: str = "auto",
    mcp_mode: str = "all",
    context_mode: str = "auto",
    allow_subagents: bool = False,
    output_mode: str = "quiet",
    executor: str = "claude-code",
) -> dict[str, Any]:
    """Delegate one change-contract task through the existing pipeline."""
    import importlib

    for mod_name in ("job_manager", "classifier", "invoker", "opencode_invoker", "change_spec", "pipeline"):
        m = sys.modules.get(mod_name)
        if m is not None:
            importlib.reload(m)

    from pipeline import run_change_task_pipeline

    try:
        result = run_change_task_pipeline(
            project_root=project_root,
            change_id=change_id,
            task_id=task_id,
            correction=correction,
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
async def record_change_task_review(
    change_id: str,
    task_id: str,
    status: str,
    summary: str,
    project_root: str | None = None,
    verification_commands: list[str] | None = None,
) -> dict[str, Any]:
    """Persist the orchestrator's review outcome for a change-contract task."""
    import importlib

    m = sys.modules.get("change_spec")
    if m is not None:
        importlib.reload(m)

    from change_spec import record_task_review, task_review_to_dict

    try:
        resolved_root = Path(project_root) if project_root else Path.cwd()
        spec = record_task_review(
            resolved_root,
            change_id,
            task_id,
            status=status,
            summary=summary,
            verification_commands=verification_commands,
        )
    except Exception as exc:
        return {"error": str(exc)}

    task = next(t for t in spec.tasks if t.id == task_id)
    return {
        "change_id": spec.change_id,
        "task_id": task.id,
        "status": task.status,
        "review": task_review_to_dict(task.review),
    }


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
