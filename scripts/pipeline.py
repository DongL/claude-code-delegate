#!/usr/bin/env python3
"""Delegation pipeline — classify → envelope → invoke → compact → profile."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from change_spec import (
    ChangeSpecError,
    append_run_record,
    build_task_prompt,
    get_latest_run_record,
    get_task_readiness,
    load_change_spec,
    save_change_spec,
    validate_change_spec,
)
from classifier import Classification, classify_prompt, FLASH_MODEL, PRO_MODEL, QWEN_MODEL, build_prepared_prompt, classification_to_dict
from invoker import InvokerConfig, invoke_claude
from job_manager import (
    create_job_id,
    create_job_meta,
    find_active_lease,
    get_job_status,
    get_jobs_dir,
    persist_job_config,
    write_job_result,
)
from logger import get_logger
from profile_logger import append_profile_record, build_profile_record

_scripts_dir = os.path.dirname(os.path.abspath(__file__))
logger = get_logger("pipeline")


from compact_claude_stream import parse_compact_output


@dataclass
class DelegationResult:
    result: str
    usage: dict[str, Any]
    cost_usd: float
    terminal_reason: str
    is_error: bool
    classification: dict[str, Any]
    model: str
    effort: str
    permission_mode: str = ""
    mcp_mode: str = "all"
    task_type: str = ""
    context_budget: str = ""
    prompt_mode: str = ""
    prompt_template: str = ""
    original_prompt_chars: int = 0
    prepared_prompt_chars: int = 0
    subagents: dict[str, Any] = field(default_factory=dict)


def _resolve_auto(value: str, fallback: str) -> str:
    return value if value != "auto" else fallback


def _resolve_pipeline_config(
    model_tier: str,
    effort: str,
    permission_mode: str,
    mcp_mode: str,
    context_mode: str,
    subagent_mode: str,
    classification: Classification,
) -> dict[str, str]:
    """Resolve all auto parameters from env vars or classification fallback."""
    model = _resolve_model(model_tier, classification)
    resolved_effort = effort if effort != "auto" else os.environ.get("CLAUDE_DELEGATE_EFFORT", "auto")
    final_effort = _resolve_auto(resolved_effort, classification.effort)
    resolved_permission = permission_mode if permission_mode != "auto" else os.environ.get("CLAUDE_DELEGATE_PERMISSION_MODE", "auto")
    final_permission = _resolve_auto(resolved_permission, classification.permission_mode)
    resolved_mcp = mcp_mode if mcp_mode != "all" else os.environ.get("CLAUDE_DELEGATE_MCP_MODE", "all")
    resolved_context = context_mode if context_mode != "auto" else os.environ.get("CLAUDE_DELEGATE_CONTEXT_MODE", "auto")
    resolved_subagents = subagent_mode if subagent_mode != "off" else (
        "on" if os.environ.get("CLAUDE_DELEGATE_SUBAGENTS", "").lower() == "on" else "off"
    )
    return {
        "model": model,
        "effort": final_effort,
        "permission_mode": final_permission,
        "mcp_mode": resolved_mcp,
        "context_mode": resolved_context,
        "subagent_mode": resolved_subagents,
    }


def _resolve_model(model_tier: str, classification: Classification) -> str:
    env_model = os.environ.get("CLAUDE_DELEGATE_MODEL")
    if env_model:
        return env_model
    if model_tier == "flash":
        return FLASH_MODEL
    if model_tier == "pro":
        return PRO_MODEL
    if model_tier == "qwen":
        return QWEN_MODEL
    return classification.model


def _count_subagent_stream_events(raw_output: str) -> int | None:
    """Count Task/Agent tool-use events in stream-json output. Conservative: returns None on any parse failure."""
    import json
    count = 0
    found_any = False
    for line in raw_output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        msg = event.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") in ("Task", "Agent"):
                count += 1
                found_any = True
    return count if found_any else None


def run_delegation_pipeline(
    prompt: str,
    *,
    model_tier: str = "auto",
    effort: str = "auto",
    permission_mode: str = "auto",
    mcp_mode: str = "all",
    context_mode: str = "auto",
    subagent_mode: str = "off",
    output_mode: str = "quiet",
    executor: str = "claude-code",
) -> DelegationResult:
    # 1. Classification
    classification = classify_prompt(prompt)
    logger.debug(
        "classification result",
        task_type=classification.task_type,
        model=classification.model,
        effort=classification.effort,
    )

    # 2. Resolve overrides — env var consulted only when parameter is "auto"
    resolved = _resolve_pipeline_config(
        model_tier, effort, permission_mode, mcp_mode, context_mode, subagent_mode, classification,
    )
    model = resolved["model"]
    final_effort = resolved["effort"]
    final_permission = resolved["permission_mode"]
    resolved_mcp = resolved["mcp_mode"]
    resolved_context = resolved["context_mode"]
    resolved_subagents = resolved["subagent_mode"]

    # 3. Subagent metadata
    allowed = resolved_subagents == "on"
    subagents: dict[str, Any] = {
        "mode": resolved_subagents,
        "allowed": allowed,
        "observed_count": 0 if not allowed else None,
        "observed_source": "disabled" if not allowed else "not_observable_in_quiet_json",
    }

    # 4. Build prepared prompt
    final_prompt, prompt_mode = build_prepared_prompt(prompt, classification, resolved_context)

    # Validate prompt is non-empty before invoking executor
    if not final_prompt or not final_prompt.strip():
        logger.error("built prompt is empty — classification or template may have failed")
        return DelegationResult(
            result="",
            usage={},
            cost_usd=0.0,
            terminal_reason="empty_prompt",
            is_error=True,
            classification=classification_to_dict(classification),
            model=model,
            effort=final_effort,
            permission_mode=final_permission,
            mcp_mode=resolved_mcp,
            task_type=classification.task_type,
            context_budget=classification.context_budget,
            prompt_mode=prompt_mode,
            prompt_template="",
            original_prompt_chars=len(prompt),
            prepared_prompt_chars=0,
            subagents=subagents,
        )

    # Compute prompt metadata
    original_prompt_chars = len(prompt)
    prepared_prompt_chars = len(final_prompt)
    if prompt_mode == "template":
        prompt_template = classification.task_type
    elif prompt_mode == "envelope":
        prompt_template = "envelope"
    else:
        prompt_template = ""
    prompt_reduction_pct = max(
        0, int((1 - prepared_prompt_chars / max(original_prompt_chars, 1)) * 100)
    )

    # 5. Build InvokerConfig
    heartbeat_seconds = 30
    try:
        heartbeat_seconds = int(
            os.environ.get("CLAUDE_DELEGATE_HEARTBEAT_SECONDS", "30")
        )
    except (ValueError, TypeError):
        pass

    inactivity_timeout = 0
    try:
        inactivity_timeout = int(
            os.environ.get("CLAUDE_DELEGATE_INACTIVITY_TIMEOUT_SECONDS", "0")
        )
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
        inactivity_timeout=inactivity_timeout,
        executor=executor,
    )

    logger.debug(
        "invocation config",
        model=model,
        effort=final_effort,
        permission_mode=final_permission,
        mcp_mode=resolved_mcp,
        output_mode=output_mode,
    )

    # 6. Invoke Claude Code (heartbeat/monitor runs inside invoke_claude)
    try:
        result = invoke_claude(config)

        # 7. Parse output
        if output_mode == "stream":
            parsed = {
                "result": result.stdout,
                "usage": {},
                "cost_usd": 0.0,
                "terminal_reason": "",
                "is_error": result.returncode != 0,
            }
            if allowed:
                subagents["observed_source"] = "stream_events"
                count = _count_subagent_stream_events(result.stdout)
                if count is not None and count > 0:
                    subagents["observed_count"] = count
        else:
            parsed = parse_compact_output(result.stdout)

        # Guard: if parser returned empty result but executor produced
        # non-empty stdout, fall back to raw stdout and set diagnostic
        # terminal_reason.  Prevents MCP delegate_task from silently
        # returning success with result="" and terminal_reason="".  Some
        # OpenCode runs can complete useful work, emit plain text stdout,
        # and still exit non-zero with empty stderr; keep that output
        # available to the orchestrator instead of returning a blank result.
        if not parsed.get("result") and result.stdout.strip():
            parsed["result"] = result.stdout
            if not parsed.get("terminal_reason"):
                parsed["terminal_reason"] = (
                    "empty_result_fallback"
                    if result.returncode == 0
                    else "executor_nonzero_with_output"
                )
            if result.returncode != 0 and not result.stderr.strip():
                parsed["is_error"] = False

        if result.returncode != 0:
            logger.error(
                "claude invocation failed",
                returncode=result.returncode,
                stderr_tail=result.stderr[-500:] if result.stderr else "",
            )
    except Exception as exc:
        logger.error("claude invocation exception", error=str(exc))
        raise

    # 8. Profile logging
    profile_log = os.environ.get("CLAUDE_DELEGATE_PROFILE_LOG")
    if profile_log:
        record = build_profile_record(
            model=model,
            effort=final_effort,
            permission_mode=final_permission,
            mcp_mode=resolved_mcp,
            task_class=classification.name,
            task_type=classification.task_type,
            context_budget=classification.context_budget,
            prompt_mode=prompt_mode,
            prompt_template=prompt_template,
            original_prompt_chars=original_prompt_chars,
            prepared_prompt_chars=prepared_prompt_chars,
            prompt_reduction_pct=prompt_reduction_pct,
            usage=parsed.get("usage"),
            total_cost_usd=parsed.get("cost_usd"),
            terminal_reason=parsed.get("terminal_reason"),
            is_error=bool(parsed.get("is_error")),
            subagents=subagents,
        )
        append_profile_record(record, profile_log)

    return DelegationResult(
        result=parsed.get("result", ""),
        usage=parsed.get("usage", {}),
        cost_usd=parsed.get("cost_usd", 0.0),
        terminal_reason=parsed.get("terminal_reason", ""),
        is_error=bool(parsed.get("is_error")),
        classification=classification_to_dict(classification),
        model=model,
        effort=final_effort,
        permission_mode=final_permission,
        mcp_mode=resolved_mcp,
        task_type=classification.task_type,
        context_budget=classification.context_budget,
        prompt_mode=prompt_mode,
        prompt_template=prompt_template,
        original_prompt_chars=original_prompt_chars,
        prepared_prompt_chars=prepared_prompt_chars,
        subagents=subagents,
    )


def start_delegation_async(
    prompt: str,
    *,
    model_tier: str = "auto",
    effort: str = "auto",
    permission_mode: str = "auto",
    mcp_mode: str = "all",
    context_mode: str = "auto",
    subagent_mode: str = "off",
    output_mode: str = "quiet",
    executor: str = "claude-code",
) -> dict[str, Any]:
    """Start an async delegation.  Returns a dict with job_id and status.

    Enforces single-flight: if another job is already running the active
    lease is returned instead of starting a duplicate delegation.
    """
    existing = find_active_lease()
    if existing is not None:
        return {
            "status": "lease_held",
            "job_id": existing["job_id"],
            "pid": existing.get("pid"),
            "started_at": existing.get("started_at", ""),
            "model": existing.get("model", ""),
            "effort": existing.get("effort", ""),
            "message": (
                "Another delegation job is running. "
                "Poll its status or wait for completion. "
                "No retry, reduced correction plan, or second delegation "
                "is allowed while the original job is still running."
            ),
        }

    classification = classify_prompt(prompt)
    logger.debug(
        "async classification",
        task_type=classification.task_type,
        model=classification.model,
    )

    resolved = _resolve_pipeline_config(
        model_tier, effort, permission_mode, mcp_mode, context_mode, subagent_mode, classification,
    )
    model = resolved["model"]
    final_effort = resolved["effort"]
    final_permission = resolved["permission_mode"]
    resolved_mcp = resolved["mcp_mode"]
    resolved_subagents = resolved["subagent_mode"]

    final_prompt, _ = build_prepared_prompt(prompt, classification, context_mode)
    
    if not final_prompt or not final_prompt.strip():
        return {
                "status": "failed",
                "job_id": "",
                "error": "empty prompt after classification"
        }

    _heartbeat = 0
    try:
        _heartbeat = int(
            os.environ.get("CLAUDE_DELEGATE_HEARTBEAT_SECONDS", "0")
        )
    except (ValueError, TypeError):
        pass

    config = InvokerConfig(
        model=model,
        effort=final_effort,
        permission_mode=final_permission,
        mcp_mode=resolved_mcp,
        subagent_mode=resolved_subagents,
        heartbeat_seconds=_heartbeat,
        output_mode=output_mode,
        prompt=final_prompt,
        inactivity_timeout=0,
        executor=executor,
    )

    import subprocess
    import sys

    job_id = create_job_id()
    jobs_dir = get_jobs_dir()
    job_dir = jobs_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    # Write config before launching supervisor (supervisor reads config.json)
    from dataclasses import asdict

    persist_job_config(job_id, asdict(config))

    run_pipeline = os.path.join(_scripts_dir, "run-pipeline.py")

    logger.debug(
        "spawning supervisor",
        job_id=job_id,
        model=model,
        effort=final_effort,
        permission_mode=final_permission,
        mcp_mode=resolved_mcp,
        output_mode=output_mode,
    )

    supervisor_proc = subprocess.Popen(
        [sys.executable, run_pipeline, "--supervise", job_id],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Create meta.json with the supervisor PID so find_active_lease and
    # polling follow the process responsible for recording result.json.
    # The Claude child PID is stored separately by the supervisor.
    create_job_meta(
        job_id=job_id,
        pid=supervisor_proc.pid,
        prompt=final_prompt,
        model=model,
        effort=final_effort,
        permission_mode=final_permission,
        mcp_mode=resolved_mcp,
        output_mode=output_mode,
        subagent_mode=resolved_subagents,
    )

    logger.info(
        "async job started with detached supervisor",
        job_id=job_id,
        pid=supervisor_proc.pid,
        model=model,
        effort=final_effort,
    )

    return {
        "status": "running",
        "job_id": job_id,
        "pid": supervisor_proc.pid,
        "started_at": "just now",
        "model": model,
        "effort": final_effort,
        "subagent_mode": resolved_subagents,
        "lease_active": True,
    }


def poll_delegation_status(job_id: str) -> dict[str, Any]:
    """Poll the status of an async delegation job.

    If completed, parses the stdout as compact JSON output and includes
    the parsed result.  If running, includes file-size and tail info.
    """
    status = get_job_status(job_id)

    if status["status"] == "completed":
        try:
            parsed = parse_compact_output(status["stdout"])

            # Same guard as run_delegation_pipeline: don't silently return
            # empty success when stdout has content.
            if not parsed.get("result") and status.get("stdout", "").strip():
                parsed["result"] = status["stdout"]
                if not parsed.get("terminal_reason"):
                    parsed["terminal_reason"] = (
                        "empty_result_fallback"
                        if status.get("returncode", 0) == 0
                        else "executor_nonzero_with_output"
                    )

            subagent_mode = status.get("subagent_mode", "off")
            allowed = subagent_mode == "on"
            return {
                "status": "completed",
                "job_id": job_id,
                "result": parsed.get("result", ""),
                "usage": parsed.get("usage", {}),
                "cost_usd": parsed.get("cost_usd", 0.0),
                "terminal_reason": parsed.get("terminal_reason", ""),
                "model": parsed.get("model", ""),
                "effort": parsed.get("effort", ""),
                "subagents": {
                    "mode": subagent_mode,
                    "allowed": allowed,
                    "observed_count": 0 if not allowed else None,
                    "observed_source": "disabled" if not allowed else "not_observable_in_quiet_json",
                },
            }
        except Exception:
            return {
                "status": "failed",
                "job_id": job_id,
                "returncode": status.get("returncode", -1),
                "stderr_tail": "completed output could not be parsed",
            }

    if (
        status["status"] == "failed"
        and status.get("stdout_tail", "").strip()
        and not status.get("stderr_tail", "").strip()
    ):
        stdout_tail = status["stdout_tail"]
        parsed = parse_compact_output(stdout_tail)
        if not parsed.get("result"):
            parsed["result"] = stdout_tail
        if not parsed.get("terminal_reason"):
            parsed["terminal_reason"] = "executor_nonzero_with_output"

        subagent_mode = status.get("subagent_mode", "off")
        allowed = subagent_mode == "on"
        return {
            "status": "completed",
            "job_id": job_id,
            "returncode": status.get("returncode", -1),
            "result": parsed.get("result", ""),
            "usage": parsed.get("usage", {}),
            "cost_usd": parsed.get("cost_usd", 0.0),
            "terminal_reason": parsed.get("terminal_reason", ""),
            "model": parsed.get("model", ""),
            "effort": parsed.get("effort", ""),
            "subagents": {
                "mode": subagent_mode,
                "allowed": allowed,
                "observed_count": 0 if not allowed else None,
                "observed_source": "disabled" if not allowed else "not_observable_in_quiet_json",
            },
        }

    return status


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_change_task_pipeline(
    *,
    project_root: str | None = None,
    change_id: str,
    task_id: str,
    correction: str | None = None,
    **pipeline_options: Any,
) -> DelegationResult:
    """Delegate one change-contract task through the existing pipeline.

    ``project_root`` locates the change-contract files under
    ``.claude-delegate/changes/`` only (PRD sections 6.3.1 and 16); it is
    never forwarded to InvokerConfig or invoke_claude. Extra
    ``pipeline_options`` (model_tier, effort, permission_mode, mcp_mode,
    context_mode, subagent_mode, output_mode, executor) pass straight through
    to the unmodified ``run_delegation_pipeline``.
    """
    resolved_root = Path(project_root) if project_root is not None else Path.cwd()

    spec = load_change_spec(resolved_root, change_id)
    validate_change_spec(spec)

    task = next((t for t in spec.tasks if t.id == task_id), None)
    if task is None:
        raise ChangeSpecError(f"unknown task id {task_id!r} in change {change_id!r}")

    ready, reasons = get_task_readiness(spec, task_id)
    if not ready:
        raise ChangeSpecError(
            f"task {task_id!r} in change {change_id!r} is not ready for delegation: "
            + "; ".join(reasons)
        )

    previous_result = None
    if correction is not None:
        latest_run = get_latest_run_record(resolved_root, change_id)
        if latest_run is not None:
            previous_result = latest_run.get("result")

    prompt = build_task_prompt(spec, task_id, correction=correction, previous_result=previous_result)

    started_at = _utc_now_iso()
    result = run_delegation_pipeline(prompt, **pipeline_options)
    completed_at = _utc_now_iso()

    append_run_record(
        resolved_root,
        change_id,
        {
            "schema_version": 1,
            "task_id": task_id,
            "started_at": started_at,
            "completed_at": completed_at,
            "correction": correction,
            "executor": pipeline_options.get("executor", "claude-code"),
            "model": result.model,
            "effort": result.effort,
            "permission_mode": result.permission_mode,
            "mcp_mode": result.mcp_mode,
            "task_type": result.task_type,
            "terminal_reason": result.terminal_reason,
            "is_error": result.is_error,
            "cost_usd": result.cost_usd,
            "usage": result.usage,
            "result": result.result,
        },
    )

    task.status = "failed" if result.is_error else "delegated"
    save_change_spec(resolved_root, spec)

    return result
