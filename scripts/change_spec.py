"""Persistent change-contract data model, validation, and atomic persistence.

Implements the data model, explicit validation, dependency-cycle detection,
task-readiness evaluation, atomic persistence, and task-prompt rendering
described in docs/prd/change-contracts.md (PRD section 24, implementation
tasks 1, 2, and 3).

Contracts live under ``<project_root>/.claude-delegate/changes/<change-id>/``:

    change.json      -- the ChangeSpec contract
    runs/run-NNNN.json -- one immutable delegation-run record per file

Task and requirement IDs are lowercase, hyphenated slugs (e.g. ``task-001``,
``req-001``) so rendered prompts never collide with the classifier's
uppercase ticket-reference pattern (see PRD section 21).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1

CHANGE_STATUSES = {"active", "completed", "blocked", "archived"}
TASK_STATUSES = {"pending", "delegated", "verified", "failed", "blocked", "skipped"}
REVIEW_STATUSES = {"verified", "failed", "blocked"}

# Safe slug: lowercase letters, digits, hyphens only. No path separators or "..".
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ChangeSpecError(Exception):
    """Raised when a change contract fails validation or cannot be loaded/saved."""


@dataclass(frozen=True)
class ChangeRequirement:
    id: str
    text: str
    priority: str = "must"


@dataclass
class TaskReview:
    status: str
    summary: str
    verification_commands: list[str] = field(default_factory=list)
    reviewed_at: str = ""


@dataclass
class ChangeTask:
    id: str
    title: str
    instructions: list[str]
    requirement_ids: list[str]
    depends_on: list[str] = field(default_factory=list)
    allowed_paths: list[str] = field(default_factory=list)
    forbidden_paths: list[str] = field(default_factory=list)
    verification_commands: list[str] = field(default_factory=list)
    status: str = "pending"
    review: TaskReview | None = None


@dataclass
class ChangeSpec:
    schema_version: int
    change_id: str
    title: str
    status: str
    goal: str
    non_goals: list[str]
    requirements: list[ChangeRequirement]
    tasks: list[ChangeTask]
    created_at: str
    updated_at: str


# --------------------------------------------------------------------------
# Dictionary / JSON conversion
# --------------------------------------------------------------------------


def requirement_to_dict(req: ChangeRequirement) -> dict[str, Any]:
    return {"id": req.id, "text": req.text, "priority": req.priority}


def requirement_from_dict(data: dict[str, Any]) -> ChangeRequirement:
    return ChangeRequirement(
        id=data.get("id", ""),
        text=data.get("text", ""),
        priority=data.get("priority", "must"),
    )


def task_review_to_dict(review: TaskReview | None) -> dict[str, Any] | None:
    if review is None:
        return None
    return {
        "status": review.status,
        "summary": review.summary,
        "verification_commands": list(review.verification_commands),
        "reviewed_at": review.reviewed_at,
    }


def task_review_from_dict(data: dict[str, Any] | None) -> TaskReview | None:
    if data is None:
        return None
    return TaskReview(
        status=data.get("status", ""),
        summary=data.get("summary", ""),
        verification_commands=list(data.get("verification_commands") or []),
        reviewed_at=data.get("reviewed_at", ""),
    )


def task_to_dict(task: ChangeTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "instructions": list(task.instructions),
        "requirement_ids": list(task.requirement_ids),
        "depends_on": list(task.depends_on),
        "allowed_paths": list(task.allowed_paths),
        "forbidden_paths": list(task.forbidden_paths),
        "verification_commands": list(task.verification_commands),
        "status": task.status,
        "review": task_review_to_dict(task.review),
    }


def task_from_dict(data: dict[str, Any]) -> ChangeTask:
    return ChangeTask(
        id=data.get("id", ""),
        title=data.get("title", ""),
        instructions=list(data.get("instructions") or []),
        requirement_ids=list(data.get("requirement_ids") or []),
        depends_on=list(data.get("depends_on") or []),
        allowed_paths=list(data.get("allowed_paths") or []),
        forbidden_paths=list(data.get("forbidden_paths") or []),
        verification_commands=list(data.get("verification_commands") or []),
        status=data.get("status", "pending"),
        review=task_review_from_dict(data.get("review")),
    )


def change_spec_to_dict(spec: ChangeSpec) -> dict[str, Any]:
    return {
        "schema_version": spec.schema_version,
        "change_id": spec.change_id,
        "title": spec.title,
        "status": spec.status,
        "goal": spec.goal,
        "non_goals": list(spec.non_goals),
        "requirements": [requirement_to_dict(r) for r in spec.requirements],
        "tasks": [task_to_dict(t) for t in spec.tasks],
        "created_at": spec.created_at,
        "updated_at": spec.updated_at,
    }


def change_spec_from_dict(data: dict[str, Any]) -> ChangeSpec:
    if not isinstance(data, dict):
        raise ChangeSpecError(
            f"change contract must be a JSON object, got {type(data).__name__}"
        )
    return ChangeSpec(
        schema_version=data.get("schema_version"),
        change_id=data.get("change_id", ""),
        title=data.get("title", ""),
        status=data.get("status", ""),
        goal=data.get("goal", ""),
        non_goals=list(data.get("non_goals") or []),
        requirements=[requirement_from_dict(r) for r in data.get("requirements") or []],
        tasks=[task_from_dict(t) for t in data.get("tasks") or []],
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
    )


def change_spec_to_json(spec: ChangeSpec) -> str:
    return json.dumps(change_spec_to_dict(spec), indent=2, ensure_ascii=False) + "\n"


def change_spec_from_json(text: str) -> ChangeSpec:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ChangeSpecError(f"invalid JSON: {exc}") from exc
    return change_spec_from_dict(data)


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def _is_valid_slug(value: object) -> bool:
    return isinstance(value, str) and bool(_SLUG_RE.match(value))


def _is_safe_relative_path(path: object) -> bool:
    if not isinstance(path, str) or not path.strip():
        return False
    if path.startswith("/") or path.startswith("\\"):
        return False
    if re.match(r"^[A-Za-z]:[\\/]", path):
        return False
    segments = re.split(r"[\\/]+", path)
    return ".." not in segments


def find_dependency_cycle(tasks: list[ChangeTask]) -> list[str] | None:
    """Return a cycle as a closed path of task IDs if one exists, else None.

    Self-dependencies are ignored here; that case is a separate validation
    rule (a task may not depend on itself) with its own dedicated message.
    Edges to unknown task IDs are ignored too; missing-reference validation
    is a separate rule, and this function must not raise on a dangling ID.
    """
    graph = {t.id: [d for d in t.depends_on if d != t.id] for t in tasks}
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {task_id: WHITE for task_id in graph}
    path_stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        color[node] = GRAY
        path_stack.append(node)
        for dep in graph.get(node, ()):
            if dep not in graph:
                continue
            if color[dep] == GRAY:
                cycle_start = path_stack.index(dep)
                return path_stack[cycle_start:] + [dep]
            if color[dep] == WHITE:
                found = visit(dep)
                if found is not None:
                    return found
        path_stack.pop()
        color[node] = BLACK
        return None

    for task_id in graph:
        if color[task_id] == WHITE:
            found = visit(task_id)
            if found is not None:
                return found
    return None


def collect_validation_errors(spec: ChangeSpec) -> list[str]:
    """Return all practical validation failures for ``spec`` (empty if valid)."""
    errors: list[str] = []

    # Rule 1: schema_version must be exactly int 1.
    version = spec.schema_version
    if isinstance(version, bool) or version != 1:
        errors.append(f"schema_version must be exactly int 1; got {version!r}")

    # Rule 2: change_id is a safe, non-empty slug.
    if not _is_valid_slug(spec.change_id):
        errors.append(
            f"change_id {spec.change_id!r} must be a non-empty slug of lowercase "
            "letters, digits, and hyphens, with no path separators or '..'"
        )

    # Rule 13 (change status half): change status recognized.
    if spec.status not in CHANGE_STATUSES:
        errors.append(
            f"change status {spec.status!r} is not one of {sorted(CHANGE_STATUSES)}"
        )

    # Rule 3: requirement IDs unique (+ slug format).
    req_ids_seen: set[str] = set()
    req_id_dupes: set[str] = set()
    for req in spec.requirements:
        if not _is_valid_slug(req.id):
            errors.append(
                f"requirement id {req.id!r} must be a lowercase, hyphenated slug "
                "(e.g. 'req-001')"
            )
        if req.id in req_ids_seen:
            req_id_dupes.add(req.id)
        req_ids_seen.add(req.id)
    for dupe in sorted(req_id_dupes):
        errors.append(f"duplicate requirement id: {dupe!r}")

    # Rule 4: task IDs unique (+ slug format).
    task_ids_seen: set[str] = set()
    task_id_dupes: set[str] = set()
    for task in spec.tasks:
        if not _is_valid_slug(task.id):
            errors.append(
                f"task id {task.id!r} must be a lowercase, hyphenated slug "
                "(e.g. 'task-001')"
            )
        if task.id in task_ids_seen:
            task_id_dupes.add(task.id)
        task_ids_seen.add(task.id)
    for dupe in sorted(task_id_dupes):
        errors.append(f"duplicate task id: {dupe!r}")

    for task in spec.tasks:
        # Rule 9: at least one instruction.
        if not task.instructions:
            errors.append(f"task {task.id!r} must contain at least one instruction")

        # Rule 5: requirement_ids reference existing requirements.
        for rid in task.requirement_ids:
            if rid not in req_ids_seen:
                errors.append(
                    f"task {task.id!r} references unknown requirement id {rid!r}"
                )

        # Rule 6 & 7: depends_on reference existing tasks; no self-dependency.
        for dep in task.depends_on:
            if dep == task.id:
                errors.append(f"task {task.id!r} cannot depend on itself")
            elif dep not in task_ids_seen:
                errors.append(f"task {task.id!r} depends on unknown task id {dep!r}")

        # Rule 11: allowed/forbidden paths must be safe and repository-relative.
        for p in task.allowed_paths:
            if not _is_safe_relative_path(p):
                errors.append(
                    f"task {task.id!r} allowed_paths entry {p!r} must be a safe, "
                    "repository-relative path"
                )
        for p in task.forbidden_paths:
            if not _is_safe_relative_path(p):
                errors.append(
                    f"task {task.id!r} forbidden_paths entry {p!r} must be a safe, "
                    "repository-relative path"
                )

        # Rule 12: exact duplicates between allowed/forbidden are rejected;
        # prefix overlaps (e.g. a directory vs. a file under it) are fine —
        # forbidden_paths takes precedence at prompt-render time (PRD §15).
        for p in sorted(set(task.allowed_paths) & set(task.forbidden_paths)):
            errors.append(
                f"task {task.id!r} path {p!r} appears in both allowed_paths and "
                "forbidden_paths"
            )

        # Rule 13 (task status half): task status recognized.
        if task.status not in TASK_STATUSES:
            errors.append(f"task {task.id!r} has unrecognized status {task.status!r}")

        # Rule 14: review status, when present, must be a recognized outcome.
        if task.review is not None and task.review.status not in REVIEW_STATUSES:
            errors.append(
                f"task {task.id!r} review status {task.review.status!r} must be "
                f"one of {sorted(REVIEW_STATUSES)}"
            )

    # Rule 8: dependency graph must not contain cycles.
    cycle = find_dependency_cycle(spec.tasks)
    if cycle:
        errors.append("dependency cycle detected: " + " -> ".join(cycle))

    # Rule 10: every must-have requirement is referenced by at least one task.
    covered_req_ids: set[str] = set()
    for task in spec.tasks:
        covered_req_ids.update(task.requirement_ids)
    for req in spec.requirements:
        if req.priority == "must" and req.id not in covered_req_ids:
            errors.append(f"must-have requirement {req.id!r} is not referenced by any task")

    return errors


def validate_change_spec(spec: ChangeSpec) -> None:
    """Raise ChangeSpecError with every practical failure if ``spec`` is invalid."""
    errors = collect_validation_errors(spec)
    if errors:
        raise ChangeSpecError(
            f"change contract {spec.change_id!r} failed validation:\n- "
            + "\n- ".join(errors)
        )


# --------------------------------------------------------------------------
# Task readiness
# --------------------------------------------------------------------------


def _find_task(spec: ChangeSpec, task_id: str) -> ChangeTask | None:
    for task in spec.tasks:
        if task.id == task_id:
            return task
    return None


def get_task_readiness(spec: ChangeSpec, task_id: str) -> tuple[bool, list[str]]:
    """Return (is_ready, blocker_reasons) for ``task_id`` within ``spec``.

    A task is ready only when: the contract passes validation, the change is
    active, the task's own status is pending or failed, and every dependency
    task's status is verified (delegated-but-not-verified does not count).
    """
    validation_errors = collect_validation_errors(spec)
    if validation_errors:
        return False, list(validation_errors)

    reasons: list[str] = []

    if spec.status != "active":
        reasons.append(f"change {spec.change_id!r} is not active (status={spec.status!r})")

    task = _find_task(spec, task_id)
    if task is None:
        return False, [f"unknown task id {task_id!r}"]

    if task.status not in ("pending", "failed"):
        reasons.append(
            f"task {task_id!r} status is {task.status!r}, not pending or failed"
        )

    tasks_by_id = {t.id: t for t in spec.tasks}
    for dep_id in task.depends_on:
        dep = tasks_by_id.get(dep_id)
        if dep is None:
            reasons.append(f"task {task_id!r} depends on unknown task {dep_id!r}")
        elif dep.status != "verified":
            reasons.append(
                f"{task_id} is blocked because {dep_id} is {dep.status} but not verified"
            )

    return (len(reasons) == 0), reasons


# --------------------------------------------------------------------------
# Atomic persistence
# --------------------------------------------------------------------------


def _changes_root(project_root: Path) -> Path:
    return Path(project_root) / ".claude-delegate" / "changes"


def _change_dir(project_root: Path, change_id: str) -> Path:
    return _changes_root(project_root) / change_id


def _change_file(project_root: Path, change_id: str) -> Path:
    return _change_dir(project_root, change_id) / "change.json"


def _runs_dir(project_root: Path, change_id: str) -> Path:
    return _change_dir(project_root, change_id) / "runs"


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write ``data`` to ``path`` atomically: temp file in the same dir, then
    write+flush+fsync, then os.replace. A failure at any point before the
    final os.replace leaves the pre-existing file at ``path`` untouched.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, str(path))
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def load_change_spec(project_root: Path, change_id: str) -> ChangeSpec:
    path = _change_file(project_root, change_id)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ChangeSpecError(
            f"no change contract found for change_id={change_id!r} at {path}"
        ) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ChangeSpecError(f"change contract at {path} is not valid JSON: {exc}") from exc
    return change_spec_from_dict(data)


def save_change_spec(project_root: Path, spec: ChangeSpec) -> Path:
    path = _change_file(project_root, spec.change_id)
    _atomic_write_json(path, change_spec_to_dict(spec))
    return path


def list_change_specs(project_root: Path) -> list[ChangeSpec]:
    root = _changes_root(project_root)
    if not root.exists():
        return []
    specs: list[ChangeSpec] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        if not (entry / "change.json").exists():
            continue
        specs.append(load_change_spec(project_root, entry.name))
    return specs


def append_run_record(project_root: Path, change_id: str, record: dict[str, Any]) -> Path:
    """Persist ``record`` as the next monotonically-numbered run file.

    Never overwrites an existing run record. Raises ChangeSpecError if the
    change contract itself does not exist yet.
    """
    change_file = _change_file(project_root, change_id)
    if not change_file.exists():
        raise ChangeSpecError(
            f"no change contract found for change_id={change_id!r} at {change_file}; "
            "cannot append a run record to a change that does not exist"
        )

    runs_dir = _runs_dir(project_root, change_id)
    runs_dir.mkdir(parents=True, exist_ok=True)

    existing_numbers = []
    for p in runs_dir.glob("run-*.json"):
        m = re.match(r"^run-(\d+)\.json$", p.name)
        if m:
            existing_numbers.append(int(m.group(1)))
    next_n = max(existing_numbers) + 1 if existing_numbers else 1
    run_id = f"run-{next_n:04d}"
    path = runs_dir / f"{run_id}.json"
    if path.exists():
        raise ChangeSpecError(f"run record {path} already exists; refusing to overwrite")

    payload = dict(record)
    payload["run_id"] = run_id
    payload["change_id"] = change_id
    _atomic_write_json(path, payload)
    return path


def get_latest_run_record(project_root: Path, change_id: str) -> dict[str, Any] | None:
    """Return the highest-numbered run record for ``change_id``, or None if
    no run has been recorded yet. Used to surface the previous executor
    result for a correction pass (PRD section 16, step 6).
    """
    runs_dir = _runs_dir(project_root, change_id)
    if not runs_dir.exists():
        return None
    numbered: list[tuple[int, Path]] = []
    for p in runs_dir.glob("run-*.json"):
        m = re.match(r"^run-(\d+)\.json$", p.name)
        if m:
            numbered.append((int(m.group(1)), p))
    if not numbered:
        return None
    _, latest_path = max(numbered, key=lambda pair: pair[0])
    try:
        return json.loads(latest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ChangeSpecError(f"run record at {latest_path} is not valid JSON: {exc}") from exc


# --------------------------------------------------------------------------
# Review recording (PRD section 18)
# --------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_task_review(
    project_root: Path,
    change_id: str,
    task_id: str,
    *,
    status: str,
    summary: str,
    verification_commands: list[str] | None = None,
) -> ChangeSpec:
    """Persist the orchestrator's review outcome for one task (PRD section 18).

    Only the external orchestrator calls this; ``status`` is taken exactly as
    given and never inferred from ``summary`` or executor text (PRD sections
    6.4, 11).
    """
    if status not in REVIEW_STATUSES:
        raise ChangeSpecError(
            f"review status {status!r} must be one of {sorted(REVIEW_STATUSES)}"
        )

    spec = load_change_spec(project_root, change_id)
    task = _find_task(spec, task_id)
    if task is None:
        raise ChangeSpecError(f"unknown task id {task_id!r} in change {change_id!r}")

    task.status = status
    task.review = TaskReview(
        status=status,
        summary=summary,
        verification_commands=list(verification_commands or []),
        reviewed_at=_utc_now_iso(),
    )
    save_change_spec(project_root, spec)
    return spec


# --------------------------------------------------------------------------
# Task prompt rendering (PRD section 15)
# --------------------------------------------------------------------------


def _bullet_list(items: list[str]) -> str:
    if not items:
        return "(none)"
    return "\n".join(f"- {item}" for item in items)


def _numbered_list(items: list[str]) -> str:
    if not items:
        return "(none)"
    return "\n".join(f"{i}. {item}" for i, item in enumerate(items, start=1))


_CONSTRAINTS_BLOCK = "\n".join(
    [
        "Constraints",
        "- Do not broaden the scope.",
        "- Do not revert unrelated user changes.",
        "- Do not modify forbidden paths.",
        "- Prefer surgical changes.",
        "- Do not add speculative abstractions.",
        "- Preserve behavior outside the stated requirements.",
    ]
)

_REQUIRED_FINAL_REPORT_BLOCK = "\n".join(
    [
        "Required Final Report",
        "- List changed files.",
        "- List commands executed.",
        "- Report verification results.",
        "- Report unresolved issues or deviations.",
    ]
)


def build_task_prompt(
    spec: ChangeSpec,
    task_id: str,
    *,
    correction: str | None = None,
    previous_result: str | None = None,
) -> str:
    """Render the plain-string executor prompt for ``task_id`` (PRD section 15).

    Ownership boundaries always render allowed paths before forbidden paths,
    so the executor reads the exclusion last: forbidden_paths takes
    precedence over allowed_paths on any prefix overlap (PRD section 12,
    rule 12). When ``correction`` is given, a correction-pass appendix is
    added carrying the prior executor result and the orchestrator's review.
    """
    task = _find_task(spec, task_id)
    if task is None:
        raise ChangeSpecError(f"unknown task id {task_id!r} in change {spec.change_id!r}")

    reqs_by_id = {r.id: r for r in spec.requirements}
    requirement_lines = [f"- {rid}: {reqs_by_id[rid].text}" for rid in task.requirement_ids]

    blocks = [
        "\n".join(
            ["Change", f"ID: {spec.change_id}", f"Title: {spec.title}", f"Goal: {spec.goal}"]
        ),
        "Non-Goals\n" + _bullet_list(spec.non_goals),
        "\n".join(["Task", f"ID: {task.id}", f"Title: {task.title}"]),
        "Requirements\n" + ("\n".join(requirement_lines) or "(none)"),
        "Instructions\n" + _numbered_list(task.instructions),
        (
            "Ownership Boundaries\n\n"
            "Allowed paths:\n" + _bullet_list(task.allowed_paths) + "\n\n"
            "Forbidden paths (take precedence over allowed paths above):\n"
            + _bullet_list(task.forbidden_paths)
        ),
        _CONSTRAINTS_BLOCK,
        "Verification\n" + _bullet_list(task.verification_commands),
        _REQUIRED_FINAL_REPORT_BLOCK,
    ]

    prompt = "\n\n".join(blocks)

    if correction is not None:
        correction_block = "\n".join(
            [
                "Correction Pass",
                "",
                "Previous executor result:",
                previous_result if previous_result is not None else "(no previous result available)",
                "",
                "Orchestrator review:",
                correction,
                "",
                "Fix only the reviewed defects.",
                "Preserve all correct parts of the existing implementation.",
                "Do not broaden scope.",
                "Re-run the original verification commands.",
            ]
        )
        prompt = prompt + "\n\n" + correction_block

    return prompt
