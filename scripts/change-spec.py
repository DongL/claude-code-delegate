#!/usr/bin/env python3
"""Standalone change-contract management CLI (PRD docs/prd/change-contracts.md
section 20).

Subcommands:

    validate <change-id>
    show <change-id>
    list
    review <change-id> <task-id> --status STATUS --summary TEXT
           [--verification-commands CMD ...]

All subcommands accept an optional ``--project-root`` (default: cwd). This
script only reads/writes change contracts via scripts/change_spec.py -- it
does not duplicate validation, persistence, or review-recording logic.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_scripts_dir = os.path.dirname(os.path.abspath(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from change_spec import (
    ChangeSpecError,
    change_spec_to_json,
    collect_validation_errors,
    list_change_specs,
    load_change_spec,
    record_task_review,
)


def _resolve_project_root(args: argparse.Namespace) -> Path:
    return Path(args.project_root) if args.project_root else Path.cwd()


def _cmd_validate(args: argparse.Namespace) -> int:
    project_root = _resolve_project_root(args)
    try:
        spec = load_change_spec(project_root, args.change_id)
    except ChangeSpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    errors = collect_validation_errors(spec)
    if errors:
        print(f"change {args.change_id!r} is invalid:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"change {args.change_id!r} is valid")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    project_root = _resolve_project_root(args)
    try:
        spec = load_change_spec(project_root, args.change_id)
    except ChangeSpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    sys.stdout.write(change_spec_to_json(spec))
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    project_root = _resolve_project_root(args)
    specs = list_change_specs(project_root)
    if not specs:
        print("no change contracts found")
        return 0

    for spec in specs:
        counts: dict[str, int] = {}
        for task in spec.tasks:
            counts[task.status] = counts.get(task.status, 0) + 1
        counts_str = ", ".join(f"{status}={n}" for status, n in sorted(counts.items()))
        print(f"{spec.change_id}\tstatus={spec.status}\ttasks={len(spec.tasks)} ({counts_str})")
    return 0


def _cmd_review(args: argparse.Namespace) -> int:
    project_root = _resolve_project_root(args)
    try:
        record_task_review(
            project_root,
            args.change_id,
            args.task_id,
            status=args.status,
            summary=args.summary,
            verification_commands=args.verification_commands,
        )
    except ChangeSpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"recorded review for {args.change_id}/{args.task_id}: {args.status}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="change-spec.py",
        description="Manage claude-code-delegate change contracts.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate a change contract.")
    validate_parser.add_argument("change_id")
    validate_parser.add_argument("--project-root", default=None)
    validate_parser.set_defaults(func=_cmd_validate)

    show_parser = subparsers.add_parser("show", help="Print a change contract as JSON.")
    show_parser.add_argument("change_id")
    show_parser.add_argument("--project-root", default=None)
    show_parser.set_defaults(func=_cmd_show)

    list_parser = subparsers.add_parser(
        "list", help="List change contracts and per-status task counts."
    )
    list_parser.add_argument("--project-root", default=None)
    list_parser.set_defaults(func=_cmd_list)

    review_parser = subparsers.add_parser(
        "review", help="Record an orchestrator review outcome for one task."
    )
    review_parser.add_argument("change_id")
    review_parser.add_argument("task_id")
    review_parser.add_argument(
        "--status", required=True, choices=["verified", "failed", "blocked"]
    )
    review_parser.add_argument("--summary", required=True)
    review_parser.add_argument(
        "--verification-commands",
        nargs="*",
        default=None,
        metavar="CMD",
        dest="verification_commands",
        help="Commands the orchestrator actually checked.",
    )
    review_parser.add_argument("--project-root", default=None)
    review_parser.set_defaults(func=_cmd_review)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
