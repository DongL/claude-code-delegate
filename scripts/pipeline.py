#!/usr/bin/env python3
"""Delegation pipeline — classify → envelope → invoke → compact → profile."""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from typing import Any

from classifier import Classification, classify_prompt, FLASH_MODEL, PRO_MODEL
from envelope_builder import build_prepared_prompt
from invoker import InvokerConfig, invoke_claude
from profile_logger import append_profile_record, build_profile_record

_scripts_dir = os.path.dirname(os.path.abspath(__file__))


def _import_hyphenated(name: str):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"),
        os.path.join(_scripts_dir, f"{name}.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_compact = _import_hyphenated("compact-claude-stream")
parse_compact_output = _compact.parse_compact_output


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


def _resolve_auto(value: str, fallback: str) -> str:
    return value if value != "auto" else fallback


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


def _resolve_model(model_tier: str, classification: Classification) -> str:
    env_model = os.environ.get("CLAUDE_DELEGATE_MODEL")
    if env_model:
        return env_model
    if model_tier == "flash":
        return FLASH_MODEL
    if model_tier == "pro":
        return PRO_MODEL
    return classification.model


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
) -> DelegationResult:
    # 1. Classification
    classification = classify_prompt(prompt)

    # 2. Resolve overrides — env var consulted only when parameter is "auto"
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

    # 3. Build prepared prompt
    final_prompt, prompt_mode = build_prepared_prompt(prompt, classification, resolved_context)

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

    # 4. Build InvokerConfig
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
    )

    # 5. Invoke Claude Code (heartbeat/monitor runs inside invoke_claude)
    try:
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
            parsed = parse_compact_output(result.stdout)
    finally:
        pass  # daemon threads (reader, monitor) clean up automatically

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
        )
        append_profile_record(record, profile_log)

    return DelegationResult(
        result=parsed.get("result", ""),
        usage=parsed.get("usage", {}),
        cost_usd=parsed.get("cost_usd", 0.0),
        terminal_reason=parsed.get("terminal_reason", ""),
        is_error=bool(parsed.get("is_error")),
        classification=_classification_to_dict(classification),
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
    )
