#!/usr/bin/env python3
"""Parse Claude Code stream-json output."""

from __future__ import annotations

import json
import os
from typing import Any


def parse_claude_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Parse a list of Claude Code stream-json events.

    Expected event types: system/init, result, and is_error markers.
    Returns the standard parsed dict with result, usage, cost, etc.
    """
    init: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    errors: list[str] = []

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

    usage = (result or {}).get("usage")
    cost_usd = (result or {}).get("total_cost_usd", 0.0)
    is_error = bool((result or {}).get("is_error"))
    terminal_reason = (result or {}).get("terminal_reason") or ""

    model = (init or {}).get("model") or os.environ.get("CLAUDE_DELEGATE_OBSERVED_MODEL")
    effort = (init or {}).get("effort") or os.environ.get("CLAUDE_DELEGATE_OBSERVED_EFFORT")
    permission_mode = (init or {}).get("permissionMode") or os.environ.get(
        "CLAUDE_DELEGATE_OBSERVED_PERMISSION_MODE"
    )
    mcp_mode = (init or {}).get("mcpMode") or os.environ.get(
        "CLAUDE_DELEGATE_OBSERVED_MCP_MODE"
    )
    cwd = (init or {}).get("cwd") or os.environ.get("CLAUDE_DELEGATE_OBSERVED_CWD")

    return {
        "result": (result or {}).get("result") or "",
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


def _deserialize(raw_json: str) -> list[dict[str, Any]]:
    """Deserialize raw JSON into a list of event dicts."""
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
                continue
            if isinstance(event, dict):
                events.append(event)
    return events
