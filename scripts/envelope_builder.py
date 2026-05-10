#!/usr/bin/env python3
"""Prompt envelope builder for Claude Code delegation."""

from __future__ import annotations

from classifier import Classification

KARPATHY_GUIDELINES = (
    "Coding Guidelines:\n"
    "- Make surgical changes. Do not add features, refactor, or introduce abstractions beyond the task.\n"
    "- Prefer boring, simple code. Three similar lines is better than a premature abstraction.\n"
    "- Surface assumptions explicitly. If something is non-obvious, state why.\n"
    "- Define verifiable success criteria before starting. Verify with tests or commands.\n"
    "- Default to writing no comments. Add one only when the WHY is non-obvious.\n"
    "- Do not add error handling or validation for scenarios that cannot happen.\n"
    "- Do not design for hypothetical future requirements. No half-finished implementations.\n"
)


def build_prepared_prompt(prompt: str, classification: Classification, context_mode: str) -> tuple[str, str]:
    if context_mode == "full" or not classification.use_template:
        return prompt, "full"

    original = prompt.strip()
    if classification.task_type == "read_only_scan":
        return (
            "Task Template: read-only scan\n"
            f"{KARPATHY_GUIDELINES}\n"
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
            f"{KARPATHY_GUIDELINES}\n"
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
            f"{KARPATHY_GUIDELINES}\n"
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
            f"{KARPATHY_GUIDELINES}\n"
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
        f"{KARPATHY_GUIDELINES}\n"
        "Goal: preserve and execute the user's request.\n"
        "Allowed Scope: task-relevant files and tools only.\n"
        "Constraints: do not revert unrelated changes; keep changes surgical.\n"
        "Verification: run the smallest meaningful check.\n\n"
        "Original Request:\n"
        f"{original}\n",
        "envelope",
    )
