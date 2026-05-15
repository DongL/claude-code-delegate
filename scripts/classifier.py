#!/usr/bin/env python3
"""Task classifier for Claude Code delegation prompts."""

from __future__ import annotations

import re
from dataclasses import dataclass


PRO_MODEL = "deepseek-v4-pro[1m]"
FLASH_MODEL = "deepseek-v4-flash[1m]"
QWEN_MODEL = "opencode/qwen3.6-plus-free"


@dataclass(frozen=True)
class Classification:
    name: str
    task_type: str
    model: str
    effort: str
    permission_mode: str
    context_budget: str
    use_template: bool


def _has_any(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


def classify_prompt(prompt: str) -> Classification:
    text = prompt.lower()
    edit_words = ("implement", "fix", "update", "change", "write", "add", "patch")
    read_words = ("check", "show", "list", "count", "how many", "inspect", "find")
    jira_words = (
        "jira",
        "issue tracker",
        "mark ",
        "transition",
        "comment",
        "create issue",
        "update issue",
        "triage",
    )

    if "jira" in text or (
        re.search(r"\b[A-Z]+-\d+\b", prompt) and _has_any(text, jira_words)
    ):
        return Classification(
            "small", "jira_operation", FLASH_MODEL, "medium", "bypassPermissions", "standard", True
        )

    if re.search(r"\b[A-Z]+-\d+\b", prompt) and _has_any(text, edit_words):
        return Classification(
            "medium", "code_edit", PRO_MODEL, "max", "bypassPermissions", "standard", True
        )

    if _has_any(text, ("architecture", "refactor", "migration", "optimize this process", "adr")):
        return Classification(
            "large", "architecture_review", PRO_MODEL, "max", "bypassPermissions", "expanded", True
        )

    if _has_any(text, ("debug", "diagnose", "failing", "traceback", "regression", "performance")):
        return Classification(
            "medium", "code_edit", PRO_MODEL, "high", "bypassPermissions", "standard", True
        )

    if _has_any(text, edit_words):
        return Classification(
            "small", "code_edit", FLASH_MODEL, "medium", "bypassPermissions", "standard", True
        )

    if _has_any(text, read_words):
        return Classification(
            "tiny", "read_only_scan", FLASH_MODEL, "low", "bypassPermissions", "minimal", True
        )

    return Classification("default", "unknown", PRO_MODEL, "max", "bypassPermissions", "full", False)
