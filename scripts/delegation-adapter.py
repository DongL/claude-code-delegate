#!/usr/bin/env python3
"""Prepare Claude Code delegation prompts and metadata."""

from __future__ import annotations

import argparse
import re
import shlex
from dataclasses import dataclass
from pathlib import Path


PRO_MODEL = "deepseek-v4-pro[1m]"
FLASH_MODEL = "deepseek-v4-flash[1m]"


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

    if re.search(r"\b[A-Z]+-\d+\b", prompt) and _has_any(text, edit_words):
        return Classification(
            "small", "code_edit", FLASH_MODEL, "medium", "bypassPermissions", "standard", True
        )

    if "jira" in text or (
        re.search(r"\b[A-Z]+-\d+\b", prompt) and _has_any(text, jira_words)
    ):
        return Classification(
            "small", "jira_operation", FLASH_MODEL, "medium", "bypassPermissions", "standard", True
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


def build_prepared_prompt(prompt: str, classification: Classification, context_mode: str) -> tuple[str, str]:
    if context_mode == "full" or not classification.use_template:
        return prompt, "full"

    original = prompt.strip()
    if classification.task_type == "read_only_scan":
        return (
            "Task Template: read-only scan\n"
            f"Class: {classification.name}\n"
            f"Context Budget: {classification.context_budget}\n"
            "Goal: answer the user's local inspection request with the minimum necessary commands.\n"
            "Allowed Scope: read-only file, database, and shell inspection in the current project.\n"
            "Constraints: do not edit files, do not revert user changes, do not expose secrets.\n"
            "Verification: report the exact command result or the reason it could not be checked.\n\n"
            "Original Request:\n"
            f"{original}\n",
            "template",
        )

    if classification.task_type == "code_edit":
        return (
            "Task Template: code edit\n"
            f"Class: {classification.name}\n"
            f"Context Budget: {classification.context_budget}\n"
            "Goal: implement the requested code change surgically.\n"
            "Allowed Scope: files directly required by the request and adjacent focused tests.\n"
            "Constraints: do not revert unrelated changes; prefer simple, boring code; keep assumptions visible.\n"
            "Verification: run the focused checks named in the request, or the smallest relevant local test.\n\n"
            "Original Request:\n"
            f"{original}\n",
            "template",
        )

    if classification.task_type == "jira_operation":
        return (
            "Task Template: Jira operation\n"
            f"Class: {classification.name}\n"
            f"Context Budget: {classification.context_budget}\n"
            "Goal: perform the requested Jira/issue-tracker operation.\n"
            "Allowed Scope: issue tracker tools and local text utilities needed to format safe comments.\n"
            "Constraints: use clean plain text for Jira comments; do not include raw Markdown unless requested.\n"
            "Verification: report issue keys touched and the operation result.\n\n"
            "Original Request:\n"
            f"{original}\n",
            "template",
        )

    if classification.task_type == "architecture_review":
        return (
            "Task Template: architecture review\n"
            f"Class: {classification.name}\n"
            f"Context Budget: {classification.context_budget}\n"
            "Goal: evaluate or improve architecture while preserving existing behavior.\n"
            "Allowed Scope: project files relevant to the named subsystem plus focused tests/docs.\n"
            "Constraints: avoid broad rewrites; explain tradeoffs; keep changes independently reviewable.\n"
            "Verification: run focused tests or static checks that cover the touched subsystem.\n\n"
            "Original Request:\n"
            f"{original}\n",
            "template",
        )

    return (
        "Task Context Envelope\n"
        f"Class: {classification.name}\n"
        f"Task Type: {classification.task_type}\n"
        f"Context Budget: {classification.context_budget}\n"
        "Goal: preserve and execute the user's request.\n"
        "Allowed Scope: task-relevant files and tools only.\n"
        "Constraints: do not revert unrelated changes; keep changes surgical.\n"
        "Verification: run the smallest meaningful check.\n\n"
        "Original Request:\n"
        f"{original}\n",
        "envelope",
    )


def _env_line(name: str, value: str) -> str:
    return f"{name}={shlex.quote(value)}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--prompt-out", required=True)
    parser.add_argument("--env-out", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", required=True)
    parser.add_argument("--permission-mode", required=True)
    parser.add_argument("--model-explicit", choices=("0", "1"), required=True)
    parser.add_argument("--effort-explicit", choices=("0", "1"), required=True)
    parser.add_argument("--permission-explicit", choices=("0", "1"), required=True)
    parser.add_argument("--context-mode", choices=("auto", "full"), default="auto")
    args = parser.parse_args()

    classification = classify_prompt(args.prompt)
    prepared_prompt, prompt_mode = build_prepared_prompt(
        args.prompt, classification, args.context_mode
    )

    model = args.model if args.model_explicit == "1" else classification.model
    effort = args.effort if args.effort_explicit == "1" else classification.effort
    permission_mode = (
        args.permission_mode
        if args.permission_explicit == "1"
        else classification.permission_mode
    )

    original_chars = len(args.prompt)
    prepared_chars = len(prepared_prompt)
    reduction_pct = 0
    if original_chars:
        reduction_pct = max(0, round((original_chars - prepared_chars) * 100 / original_chars))

    Path(args.prompt_out).write_text(prepared_prompt, encoding="utf-8")
    Path(args.env_out).write_text(
        "\n".join(
            [
                _env_line("CLAUDE_DELEGATE_ADAPTED_MODEL", model),
                _env_line("CLAUDE_DELEGATE_ADAPTED_EFFORT", effort),
                _env_line("CLAUDE_DELEGATE_ADAPTED_PERMISSION_MODE", permission_mode),
                _env_line("CLAUDE_DELEGATE_SELECTED_CLASS", classification.name),
                _env_line("CLAUDE_DELEGATE_SELECTED_TASK_TYPE", classification.task_type),
                _env_line("CLAUDE_DELEGATE_CONTEXT_BUDGET", classification.context_budget),
                _env_line("CLAUDE_DELEGATE_PROMPT_MODE", prompt_mode),
                _env_line("CLAUDE_DELEGATE_PROMPT_TEMPLATE", classification.task_type),
                _env_line("CLAUDE_DELEGATE_ORIGINAL_PROMPT_CHARS", str(original_chars)),
                _env_line("CLAUDE_DELEGATE_PREPARED_PROMPT_CHARS", str(prepared_chars)),
                _env_line("CLAUDE_DELEGATE_PROMPT_REDUCTION_PCT", str(reduction_pct)),
                "",
            ]
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
