#!/usr/bin/env python3
"""Parse OpenCode event-stream output."""

from __future__ import annotations

import json
from typing import Any


def parse_opencode_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Parse a list of OpenCode event-stream events.

    Expected event types: text, step_finish, error.
    Returns the standard parsed dict with result, usage, cost, etc.
    """
    texts: list[str] = []
    usage: dict[str, Any] = {}
    cost: float = 0.0
    is_error: bool = False
    errors: list[str] = []

    for event in events:
        event_type = event.get("type")
        if event_type == "text":
            part = event.get("part", {})
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text", "")
                if text:
                    texts.append(text)
        elif event_type == "step_finish":
            part = event.get("part", {})
            if isinstance(part, dict):
                tokens = part.get("tokens")
                if isinstance(tokens, dict):
                    mapped: dict[str, int] = {}
                    if "input" in tokens:
                        mapped["input_tokens"] = tokens["input"]
                    if "output" in tokens:
                        mapped["output_tokens"] = tokens["output"]
                    cache_info = tokens.get("cache")
                    if isinstance(cache_info, dict):
                        read_val = cache_info.get("read", 0)
                        if isinstance(read_val, int) and read_val > 0:
                            mapped["cache_read_input_tokens"] = read_val
                    thinking_val = tokens.get("thinking")
                    if isinstance(thinking_val, int):
                        mapped["thinking_tokens"] = thinking_val
                    usage = mapped
                part_cost = part.get("cost")
                if isinstance(part_cost, (int, float)):
                    cost = part_cost
        elif event_type == "error":
            err_data = event.get("error", {})
            msg = ""
            if isinstance(err_data, dict):
                inner = err_data.get("data", {})
                if isinstance(inner, dict):
                    msg = inner.get("message", "")
                if not msg:
                    msg = err_data.get("message", "")
            if msg:
                errors.append(msg)
            is_error = True

    return {
        "result": "".join(texts),
        "usage": usage,
        "cost_usd": cost,
        "terminal_reason": "",
        "model": None,
        "effort": None,
        "permission_mode": None,
        "mcp_mode": None,
        "cwd": None,
        "subagent_count": 0,
        "is_error": is_error,
        "has_init": False,
        "has_result": bool(texts) or bool(usage),
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
