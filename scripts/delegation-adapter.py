#!/usr/bin/env python3
"""Prepare Claude Code delegation prompts and metadata."""

from __future__ import annotations

import argparse
import shlex
from pathlib import Path

from classifier import classify_prompt
from envelope_builder import build_prepared_prompt


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
