"""Unit tests for scripts/change_spec.py.

Covers PRD docs/prd/change-contracts.md section 24, implementation task 1
(data model, validation, dependency-cycle detection, task readiness) and
task 2 (atomic persistence). Stdlib unittest only -- no pytest, no
third-party packages.
"""

from __future__ import annotations

import inspect
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import change_spec as cs  # noqa: E402
import pipeline  # noqa: E402


TICKET_REF_RE = re.compile(r"\b[A-Z]+-\d+\b")


def make_requirement(**overrides) -> cs.ChangeRequirement:
    defaults = dict(id="req-001", text="Requirement text.", priority="must")
    defaults.update(overrides)
    return cs.ChangeRequirement(**defaults)


def make_task(**overrides) -> cs.ChangeTask:
    defaults = dict(
        id="task-001",
        title="Do the thing",
        instructions=["Do it."],
        requirement_ids=["req-001"],
    )
    defaults.update(overrides)
    return cs.ChangeTask(**defaults)


def make_spec(**overrides) -> cs.ChangeSpec:
    defaults = dict(
        schema_version=1,
        change_id="add-retry-policy",
        title="Add retry policy",
        status="active",
        goal="Retry transient command-execution failures.",
        non_goals=["Do not redesign the executor pipeline."],
        requirements=[make_requirement()],
        tasks=[make_task()],
        created_at="2026-07-10T00:00:00Z",
        updated_at="2026-07-10T00:00:00Z",
    )
    defaults.update(overrides)
    return cs.ChangeSpec(**defaults)


# --------------------------------------------------------------------------
# Task 1: round-trip, dictionary/JSON conversion
# --------------------------------------------------------------------------


class RoundTripTests(unittest.TestCase):
    def test_valid_contract_round_trips_without_data_loss_via_dict(self):
        spec = make_spec(
            tasks=[
                make_task(
                    depends_on=[],
                    allowed_paths=["scripts/invoker.py", "tests/"],
                    forbidden_paths=["scripts/classifier.py"],
                    verification_commands=["bash tests/run_tests.sh"],
                    review=cs.TaskReview(
                        status="verified",
                        summary="Diff limited to invoker.py and focused tests.",
                        verification_commands=["bash tests/run_tests.sh"],
                        reviewed_at="2026-07-10T00:10:00Z",
                    ),
                )
            ]
        )
        restored = cs.change_spec_from_dict(cs.change_spec_to_dict(spec))
        self.assertEqual(spec, restored)

    def test_valid_contract_round_trips_without_data_loss_via_json(self):
        spec = make_spec()
        restored = cs.change_spec_from_json(cs.change_spec_to_json(spec))
        self.assertEqual(spec, restored)

    def test_json_output_has_indent_2_and_stable_key_order(self):
        text = cs.change_spec_to_json(make_spec())
        self.assertTrue(text.startswith('{\n  "schema_version": 1,\n  "change_id": '))
        self.assertTrue(text.endswith("\n"))

    def test_json_output_is_utf8_not_escaped(self):
        text = cs.change_spec_to_json(make_spec(goal="Support café metadata."))
        self.assertIn("café", text)
        self.assertNotIn("\\u00e9", text)

    def test_review_none_round_trips_as_none(self):
        spec = make_spec(tasks=[make_task(review=None)])
        restored = cs.change_spec_from_dict(cs.change_spec_to_dict(spec))
        self.assertIsNone(restored.tasks[0].review)


# --------------------------------------------------------------------------
# Task 1: validation rule 1 -- schema_version
# --------------------------------------------------------------------------


class SchemaVersionValidationTests(unittest.TestCase):
    @staticmethod
    def _has_schema_error(errors: list[str]) -> bool:
        return any("schema_version" in e for e in errors)

    def test_missing_schema_version_is_rejected(self):
        data = cs.change_spec_to_dict(make_spec())
        del data["schema_version"]
        spec = cs.change_spec_from_dict(data)
        self.assertTrue(self._has_schema_error(cs.collect_validation_errors(spec)))

    def test_wrong_type_schema_version_is_rejected(self):
        spec = make_spec(schema_version="1")
        self.assertTrue(self._has_schema_error(cs.collect_validation_errors(spec)))

    def test_bool_schema_version_is_rejected(self):
        spec = make_spec(schema_version=True)
        self.assertTrue(self._has_schema_error(cs.collect_validation_errors(spec)))

    def test_different_integer_schema_version_is_rejected(self):
        spec = make_spec(schema_version=2)
        self.assertTrue(self._has_schema_error(cs.collect_validation_errors(spec)))

    def test_schema_version_1_is_accepted(self):
        spec = make_spec(schema_version=1)
        self.assertEqual(cs.collect_validation_errors(spec), [])
        cs.validate_change_spec(spec)  # must not raise


# --------------------------------------------------------------------------
# Task 1: validation rule 2 -- change_id
# --------------------------------------------------------------------------


class ChangeIdValidationTests(unittest.TestCase):
    def test_empty_change_id_rejected(self):
        errors = cs.collect_validation_errors(make_spec(change_id=""))
        self.assertTrue(any("change_id" in e for e in errors))

    def test_uppercase_change_id_rejected(self):
        errors = cs.collect_validation_errors(make_spec(change_id="Add-Retry-Policy"))
        self.assertTrue(any("change_id" in e for e in errors))

    def test_change_id_with_path_separator_rejected(self):
        errors = cs.collect_validation_errors(make_spec(change_id="add/retry-policy"))
        self.assertTrue(any("change_id" in e for e in errors))

    def test_change_id_with_dotdot_rejected(self):
        errors = cs.collect_validation_errors(make_spec(change_id="../escape"))
        self.assertTrue(any("change_id" in e for e in errors))

    def test_valid_change_id_accepted(self):
        self.assertEqual(cs.collect_validation_errors(make_spec(change_id="add-retry-policy")), [])


# --------------------------------------------------------------------------
# Task 1: validation rules 3 & 4 -- unique, correctly-formatted IDs
# --------------------------------------------------------------------------


class DuplicateAndFormatIdValidationTests(unittest.TestCase):
    def test_duplicate_requirement_ids_rejected(self):
        spec = make_spec(
            requirements=[make_requirement(id="req-001"), make_requirement(id="req-001", text="other")],
            tasks=[make_task(requirement_ids=["req-001"])],
        )
        errors = cs.collect_validation_errors(spec)
        self.assertTrue(any("duplicate requirement id" in e for e in errors))

    def test_duplicate_task_ids_rejected(self):
        spec = make_spec(
            tasks=[make_task(id="task-001"), make_task(id="task-001", title="dup")],
        )
        errors = cs.collect_validation_errors(spec)
        self.assertTrue(any("duplicate task id" in e for e in errors))

    def test_uppercase_task_id_rejected(self):
        spec = make_spec(tasks=[make_task(id="TASK-999")])
        errors = cs.collect_validation_errors(spec)
        self.assertTrue(any("task id" in e for e in errors))

    def test_uppercase_requirement_id_rejected(self):
        spec = make_spec(
            requirements=[make_requirement(id="REQ-999")],
            tasks=[make_task(requirement_ids=["REQ-999"])],
        )
        errors = cs.collect_validation_errors(spec)
        self.assertTrue(any("requirement id" in e for e in errors))

    def test_accepted_ids_never_collide_with_classifier_ticket_regex(self):
        # PRD section 21 (REVIEW FIX): classify_prompt's ticket-reference regex
        # is \b[A-Z]+-\d+\b. Lowercase, hyphenated IDs can never match it.
        spec = make_spec()
        for task in spec.tasks:
            self.assertIsNone(TICKET_REF_RE.search(task.id))
        for req in spec.requirements:
            self.assertIsNone(TICKET_REF_RE.search(req.id))


# --------------------------------------------------------------------------
# Task 1: validation rules 5, 6, 7 -- missing references, self-dependency
# --------------------------------------------------------------------------


class MissingReferenceValidationTests(unittest.TestCase):
    def test_unknown_requirement_reference_rejected(self):
        spec = make_spec(tasks=[make_task(requirement_ids=["req-999"])])
        errors = cs.collect_validation_errors(spec)
        self.assertTrue(any("unknown requirement id" in e for e in errors))

    def test_unknown_depends_on_reference_rejected(self):
        spec = make_spec(tasks=[make_task(depends_on=["task-999"])])
        errors = cs.collect_validation_errors(spec)
        self.assertTrue(any("depends on unknown task id" in e for e in errors))

    def test_self_dependency_rejected_and_not_double_reported_as_cycle(self):
        spec = make_spec(tasks=[make_task(id="task-001", depends_on=["task-001"])])
        errors = cs.collect_validation_errors(spec)
        self.assertTrue(any("cannot depend on itself" in e for e in errors))
        self.assertFalse(any("dependency cycle detected" in e for e in errors))


# --------------------------------------------------------------------------
# Task 1: validation rule 8 -- dependency cycles
# --------------------------------------------------------------------------


class DependencyCycleTests(unittest.TestCase):
    def test_two_node_cycle_detected(self):
        tasks = [
            make_task(id="task-001", depends_on=["task-002"], requirement_ids=[]),
            make_task(id="task-002", depends_on=["task-001"], requirement_ids=[]),
        ]
        cycle = cs.find_dependency_cycle(tasks)
        self.assertIsNotNone(cycle)
        self.assertIn("task-001", cycle)
        self.assertIn("task-002", cycle)

    def test_three_node_cycle_rejected_by_validation(self):
        spec = make_spec(
            requirements=[],
            tasks=[
                make_task(id="task-001", depends_on=["task-002"], requirement_ids=[]),
                make_task(id="task-002", depends_on=["task-003"], requirement_ids=[]),
                make_task(id="task-003", depends_on=["task-001"], requirement_ids=[]),
            ],
        )
        errors = cs.collect_validation_errors(spec)
        self.assertTrue(any("dependency cycle detected" in e for e in errors))

    def test_acyclic_dependencies_produce_no_cycle(self):
        tasks = [
            make_task(id="task-001", depends_on=[], requirement_ids=[]),
            make_task(id="task-002", depends_on=["task-001"], requirement_ids=[]),
            make_task(id="task-003", depends_on=["task-001", "task-002"], requirement_ids=[]),
        ]
        self.assertIsNone(cs.find_dependency_cycle(tasks))

    def test_self_dependency_alone_is_not_a_cycle(self):
        tasks = [make_task(id="task-001", depends_on=["task-001"], requirement_ids=[])]
        self.assertIsNone(cs.find_dependency_cycle(tasks))

    def test_cycle_ignores_dangling_edge_to_unknown_task(self):
        tasks = [make_task(id="task-001", depends_on=["task-999"], requirement_ids=[])]
        self.assertIsNone(cs.find_dependency_cycle(tasks))


# --------------------------------------------------------------------------
# Task 1: validation rule 9 -- at least one instruction
# --------------------------------------------------------------------------


class TaskInstructionValidationTests(unittest.TestCase):
    def test_task_with_no_instructions_rejected(self):
        errors = cs.collect_validation_errors(make_spec(tasks=[make_task(instructions=[])]))
        self.assertTrue(any("must contain at least one instruction" in e for e in errors))


# --------------------------------------------------------------------------
# Task 1: validation rule 10 -- must-have requirement coverage
# --------------------------------------------------------------------------


class MustHaveRequirementCoverageTests(unittest.TestCase):
    def test_uncovered_must_requirement_rejected(self):
        spec = make_spec(
            requirements=[make_requirement(id="req-001", priority="must")],
            tasks=[make_task(requirement_ids=[])],
        )
        errors = cs.collect_validation_errors(spec)
        self.assertTrue(any("must-have requirement" in e for e in errors))

    def test_covered_must_requirement_accepted(self):
        spec = make_spec(
            requirements=[make_requirement(id="req-001", priority="must")],
            tasks=[make_task(requirement_ids=["req-001"])],
        )
        self.assertEqual(cs.collect_validation_errors(spec), [])

    def test_uncovered_non_must_requirement_accepted(self):
        spec = make_spec(
            requirements=[make_requirement(id="req-002", priority="should")],
            tasks=[make_task(requirement_ids=[])],
        )
        self.assertEqual(cs.collect_validation_errors(spec), [])


# --------------------------------------------------------------------------
# Task 1: validation rule 11 -- unsafe paths
# --------------------------------------------------------------------------


class PathSafetyValidationTests(unittest.TestCase):
    def test_absolute_unix_path_rejected(self):
        errors = cs.collect_validation_errors(make_spec(tasks=[make_task(allowed_paths=["/etc/passwd"])]))
        self.assertTrue(any("allowed_paths entry" in e for e in errors))

    def test_absolute_windows_path_rejected(self):
        errors = cs.collect_validation_errors(
            make_spec(tasks=[make_task(forbidden_paths=["C:\\Windows\\System32"])])
        )
        self.assertTrue(any("forbidden_paths entry" in e for e in errors))

    def test_dotdot_path_rejected(self):
        errors = cs.collect_validation_errors(
            make_spec(tasks=[make_task(allowed_paths=["scripts/../../etc/passwd"])])
        )
        self.assertTrue(any("allowed_paths entry" in e for e in errors))

    def test_empty_path_rejected(self):
        errors = cs.collect_validation_errors(make_spec(tasks=[make_task(allowed_paths=[""])]))
        self.assertTrue(any("allowed_paths entry" in e for e in errors))

    def test_safe_relative_paths_accepted(self):
        spec = make_spec(tasks=[make_task(allowed_paths=["scripts/invoker.py", "tests/"], forbidden_paths=[])])
        self.assertEqual(cs.collect_validation_errors(spec), [])


# --------------------------------------------------------------------------
# Task 1: validation rule 12 -- allowed/forbidden overlap (REVIEW FIX)
# --------------------------------------------------------------------------


class AllowedForbiddenOverlapTests(unittest.TestCase):
    def test_exact_duplicate_between_allowed_and_forbidden_rejected(self):
        spec = make_spec(
            tasks=[make_task(allowed_paths=["scripts/classifier.py"], forbidden_paths=["scripts/classifier.py"])]
        )
        errors = cs.collect_validation_errors(spec)
        self.assertTrue(any("appears in both allowed_paths and forbidden_paths" in e for e in errors))

    def test_forbidden_file_under_allowed_directory_is_accepted(self):
        spec = make_spec(
            tasks=[make_task(allowed_paths=["scripts/"], forbidden_paths=["scripts/classifier.py"])]
        )
        self.assertEqual(cs.collect_validation_errors(spec), [])

    def test_allowed_file_under_forbidden_directory_is_accepted(self):
        # The reverse prefix direction ("or vice versa" in the task 1 acceptance criteria).
        spec = make_spec(
            tasks=[make_task(allowed_paths=["scripts/invoker.py"], forbidden_paths=["scripts/"])]
        )
        self.assertEqual(cs.collect_validation_errors(spec), [])


# --------------------------------------------------------------------------
# Task 1: validation rules 13 & 14 -- recognized statuses
# --------------------------------------------------------------------------


class StatusValidationTests(unittest.TestCase):
    def test_unrecognized_change_status_rejected(self):
        errors = cs.collect_validation_errors(make_spec(status="in-review"))
        self.assertTrue(any("change status" in e for e in errors))

    def test_unrecognized_task_status_rejected(self):
        errors = cs.collect_validation_errors(make_spec(tasks=[make_task(status="in-review")]))
        self.assertTrue(any("unrecognized status" in e for e in errors))

    def test_all_recognized_change_statuses_accepted(self):
        for status in sorted(cs.CHANGE_STATUSES):
            with self.subTest(status=status):
                self.assertEqual(cs.collect_validation_errors(make_spec(status=status)), [])

    def test_all_recognized_task_statuses_accepted(self):
        for status in sorted(cs.TASK_STATUSES):
            with self.subTest(status=status):
                spec = make_spec(tasks=[make_task(status=status)])
                self.assertEqual(cs.collect_validation_errors(spec), [])

    def test_unrecognized_review_status_rejected(self):
        spec = make_spec(tasks=[make_task(review=cs.TaskReview(status="approved", summary="ok"))])
        errors = cs.collect_validation_errors(spec)
        self.assertTrue(any("review status" in e for e in errors))

    def test_all_recognized_review_statuses_accepted(self):
        for status in sorted(cs.REVIEW_STATUSES):
            with self.subTest(status=status):
                spec = make_spec(tasks=[make_task(review=cs.TaskReview(status=status, summary="ok"))])
                self.assertEqual(cs.collect_validation_errors(spec), [])


class ValidateChangeSpecRaisesTests(unittest.TestCase):
    def test_valid_spec_does_not_raise(self):
        cs.validate_change_spec(make_spec())

    def test_invalid_spec_raises_with_every_practical_failure(self):
        spec = make_spec(schema_version=2, tasks=[make_task(instructions=[])])
        with self.assertRaises(cs.ChangeSpecError) as ctx:
            cs.validate_change_spec(spec)
        message = str(ctx.exception)
        self.assertIn("schema_version", message)
        self.assertIn("must contain at least one instruction", message)


# --------------------------------------------------------------------------
# Task 1: task readiness (PRD section 14)
# --------------------------------------------------------------------------


class TaskReadinessTests(unittest.TestCase):
    def test_ready_when_pending_with_no_dependencies(self):
        ready, reasons = cs.get_task_readiness(make_spec(), "task-001")
        self.assertTrue(ready)
        self.assertEqual(reasons, [])

    def test_not_ready_when_change_not_active(self):
        ready, reasons = cs.get_task_readiness(make_spec(status="blocked"), "task-001")
        self.assertFalse(ready)
        self.assertTrue(any("not active" in r for r in reasons))

    def test_not_ready_when_dependency_delegated_not_verified(self):
        spec = make_spec(
            requirements=[make_requirement(id="req-001")],
            tasks=[
                make_task(id="task-002", requirement_ids=["req-001"], status="delegated", depends_on=[]),
                make_task(id="task-003", requirement_ids=["req-001"], depends_on=["task-002"]),
            ],
        )
        ready, reasons = cs.get_task_readiness(spec, "task-003")
        self.assertFalse(ready)
        self.assertIn(
            "task-003 is blocked because task-002 is delegated but not verified", reasons
        )

    def test_ready_when_dependency_verified(self):
        spec = make_spec(
            requirements=[make_requirement(id="req-001")],
            tasks=[
                make_task(id="task-002", requirement_ids=["req-001"], status="verified", depends_on=[]),
                make_task(id="task-003", requirement_ids=["req-001"], depends_on=["task-002"]),
            ],
        )
        ready, reasons = cs.get_task_readiness(spec, "task-003")
        self.assertTrue(ready)
        self.assertEqual(reasons, [])

    def test_ready_when_own_status_is_failed(self):
        ready, _ = cs.get_task_readiness(make_spec(tasks=[make_task(status="failed")]), "task-001")
        self.assertTrue(ready)

    def test_not_ready_when_own_status_is_delegated(self):
        ready, reasons = cs.get_task_readiness(make_spec(tasks=[make_task(status="delegated")]), "task-001")
        self.assertFalse(ready)
        self.assertTrue(any("not pending or failed" in r for r in reasons))

    def test_unknown_task_id_not_ready(self):
        ready, reasons = cs.get_task_readiness(make_spec(), "task-999")
        self.assertFalse(ready)
        self.assertTrue(any("unknown task id" in r for r in reasons))

    def test_invalid_contract_not_ready(self):
        ready, reasons = cs.get_task_readiness(make_spec(schema_version=2), "task-001")
        self.assertFalse(ready)
        self.assertTrue(any("schema_version" in r for r in reasons))


# --------------------------------------------------------------------------
# Task 2: atomic persistence
# --------------------------------------------------------------------------


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.project_root = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_save_then_load_round_trip(self):
        spec = make_spec()
        path = cs.save_change_spec(self.project_root, spec)
        self.assertTrue(path.exists())
        self.assertEqual(cs.load_change_spec(self.project_root, spec.change_id), spec)

    def test_save_writes_deterministic_indent_and_key_order(self):
        path = cs.save_change_spec(self.project_root, make_spec())
        text = path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith('{\n  "schema_version": 1,\n  "change_id": '))

    def test_save_writes_utf8_without_escaping(self):
        path = cs.save_change_spec(self.project_root, make_spec(goal="Support café metadata."))
        self.assertIn("café", path.read_text(encoding="utf-8"))

    def test_load_missing_contract_raises_clear_error(self):
        with self.assertRaises(cs.ChangeSpecError) as ctx:
            cs.load_change_spec(self.project_root, "does-not-exist")
        self.assertIn("does-not-exist", str(ctx.exception))

    def test_load_malformed_json_raises_clear_error(self):
        change_dir = self.project_root / ".claude-delegate" / "changes" / "broken"
        change_dir.mkdir(parents=True)
        (change_dir / "change.json").write_text("{not valid json", encoding="utf-8")
        with self.assertRaises(cs.ChangeSpecError):
            cs.load_change_spec(self.project_root, "broken")

    def test_list_change_specs_empty_when_no_changes_dir(self):
        self.assertEqual(cs.list_change_specs(self.project_root), [])

    def test_list_change_specs_returns_all_saved_specs(self):
        cs.save_change_spec(self.project_root, make_spec(change_id="change-a"))
        cs.save_change_spec(self.project_root, make_spec(change_id="change-b"))
        specs = cs.list_change_specs(self.project_root)
        self.assertEqual({s.change_id for s in specs}, {"change-a", "change-b"})

    def test_project_roots_remain_isolated(self):
        with tempfile.TemporaryDirectory() as other_dir:
            other_root = Path(other_dir)
            cs.save_change_spec(self.project_root, make_spec(change_id="shared-name", title="Here"))
            cs.save_change_spec(other_root, make_spec(change_id="shared-name", title="There"))

            self.assertEqual(cs.load_change_spec(self.project_root, "shared-name").title, "Here")
            self.assertEqual(cs.load_change_spec(other_root, "shared-name").title, "There")

    def test_existing_contract_survives_failed_write(self):
        original = make_spec(title="Original")
        cs.save_change_spec(self.project_root, original)
        change_path = cs._change_file(self.project_root, original.change_id)
        original_bytes = change_path.read_bytes()

        with mock.patch("change_spec.os.replace", side_effect=OSError("simulated disk failure")):
            with self.assertRaises(OSError):
                cs.save_change_spec(self.project_root, make_spec(title="Updated"))

        self.assertEqual(change_path.read_bytes(), original_bytes)
        self.assertEqual(cs.load_change_spec(self.project_root, original.change_id).title, "Original")

    def test_failed_write_does_not_leave_temp_file_behind(self):
        spec = make_spec()
        with mock.patch("change_spec.os.replace", side_effect=OSError("simulated disk failure")):
            with self.assertRaises(OSError):
                cs.save_change_spec(self.project_root, spec)
        change_dir = cs._change_dir(self.project_root, spec.change_id)
        self.assertEqual(list(change_dir.glob("*.tmp")), [])

    def test_first_write_failure_leaves_no_partial_file(self):
        spec = make_spec()
        with mock.patch("change_spec.os.replace", side_effect=OSError("simulated disk failure")):
            with self.assertRaises(OSError):
                cs.save_change_spec(self.project_root, spec)
        self.assertFalse(cs._change_file(self.project_root, spec.change_id).exists())


class RunRecordTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.project_root = Path(self._tmpdir.name)
        self.spec = make_spec()
        cs.save_change_spec(self.project_root, self.spec)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_append_run_record_missing_change_raises(self):
        with self.assertRaises(cs.ChangeSpecError):
            cs.append_run_record(self.project_root, "does-not-exist", {"result": "x"})

    def test_run_ids_are_monotonic_and_never_overwritten(self):
        path1 = cs.append_run_record(self.project_root, self.spec.change_id, {"result": "first"})
        path2 = cs.append_run_record(self.project_root, self.spec.change_id, {"result": "second"})
        self.assertEqual(path1.name, "run-0001.json")
        self.assertEqual(path2.name, "run-0002.json")

        data1 = json.loads(path1.read_text(encoding="utf-8"))
        data2 = json.loads(path2.read_text(encoding="utf-8"))
        self.assertEqual(data1["result"], "first")
        self.assertEqual(data1["run_id"], "run-0001")
        self.assertEqual(data2["result"], "second")
        self.assertEqual(data2["run_id"], "run-0002")
        # Writing the second run record must not mutate the first one.
        self.assertEqual(json.loads(path1.read_text(encoding="utf-8"))["result"], "first")

    def test_append_run_record_skips_past_manually_created_gap(self):
        cs.append_run_record(self.project_root, self.spec.change_id, {"result": "first"})
        runs_dir = cs._runs_dir(self.project_root, self.spec.change_id)
        sentinel_path = runs_dir / "run-0002.json"
        sentinel_path.write_text('{"result": "sentinel, do not overwrite"}', encoding="utf-8")

        path3 = cs.append_run_record(self.project_root, self.spec.change_id, {"result": "third"})
        self.assertEqual(path3.name, "run-0003.json")
        self.assertIn("sentinel", sentinel_path.read_text(encoding="utf-8"))

    def test_run_record_gets_change_id_stamped(self):
        path = cs.append_run_record(self.project_root, self.spec.change_id, {"result": "x"})
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["change_id"], self.spec.change_id)

    def test_get_latest_run_record_none_when_no_runs_yet(self):
        self.assertIsNone(cs.get_latest_run_record(self.project_root, self.spec.change_id))

    def test_get_latest_run_record_returns_highest_numbered(self):
        cs.append_run_record(self.project_root, self.spec.change_id, {"result": "first"})
        cs.append_run_record(self.project_root, self.spec.change_id, {"result": "second"})
        latest = cs.get_latest_run_record(self.project_root, self.spec.change_id)
        self.assertEqual(latest["result"], "second")
        self.assertEqual(latest["run_id"], "run-0002")


# --------------------------------------------------------------------------
# Task 3: task-prompt rendering (PRD section 15)
# --------------------------------------------------------------------------


class BuildTaskPromptTests(unittest.TestCase):
    def test_returns_plain_string(self):
        prompt = cs.build_task_prompt(make_spec(), "task-001")
        self.assertIsInstance(prompt, str)

    def test_includes_change_and_task_headers(self):
        spec = make_spec(
            change_id="add-retry-policy", title="Add retry policy", goal="Retry transient failures."
        )
        prompt = cs.build_task_prompt(spec, "task-001")
        self.assertIn(
            "Change\nID: add-retry-policy\nTitle: Add retry policy\nGoal: Retry transient failures.",
            prompt,
        )
        self.assertIn("Task\nID: task-001\nTitle: Do the thing", prompt)

    def test_includes_non_goals(self):
        spec = make_spec(non_goals=["Do not redesign the executor pipeline.", "Do not add a dependency."])
        prompt = cs.build_task_prompt(spec, "task-001")
        self.assertIn(
            "Non-Goals\n- Do not redesign the executor pipeline.\n- Do not add a dependency.", prompt
        )

    def test_includes_only_requirements_referenced_by_task(self):
        spec = make_spec(
            requirements=[
                make_requirement(id="req-001", text="Covered requirement."),
                make_requirement(id="req-002", text="Other task's requirement.", priority="should"),
            ],
            tasks=[make_task(id="task-001", requirement_ids=["req-001"])],
        )
        prompt = cs.build_task_prompt(spec, "task-001")
        self.assertIn("- req-001: Covered requirement.", prompt)
        self.assertNotIn("req-002", prompt)

    def test_includes_numbered_instructions(self):
        spec = make_spec(tasks=[make_task(instructions=["First step.", "Second step."])])
        prompt = cs.build_task_prompt(spec, "task-001")
        self.assertIn("Instructions\n1. First step.\n2. Second step.", prompt)

    def test_ownership_boundaries_allowed_before_forbidden(self):
        spec = make_spec(
            tasks=[
                make_task(
                    allowed_paths=["scripts/invoker.py", "tests/"],
                    forbidden_paths=["scripts/classifier.py"],
                )
            ]
        )
        prompt = cs.build_task_prompt(spec, "task-001")
        self.assertLess(prompt.index("Allowed paths:"), prompt.index("Forbidden paths"))
        self.assertIn("Allowed paths:\n- scripts/invoker.py\n- tests/", prompt)
        self.assertIn(
            "Forbidden paths (take precedence over allowed paths above):\n- scripts/classifier.py",
            prompt,
        )

    def test_includes_exact_verification_commands(self):
        spec = make_spec(tasks=[make_task(verification_commands=["bash tests/run_tests.sh"])])
        prompt = cs.build_task_prompt(spec, "task-001")
        self.assertIn("Verification\n- bash tests/run_tests.sh", prompt)

    def test_includes_required_final_report_fields(self):
        prompt = cs.build_task_prompt(make_spec(), "task-001")
        self.assertIn("Required Final Report", prompt)
        self.assertIn("- List changed files.", prompt)
        self.assertIn("- List commands executed.", prompt)
        self.assertIn("- Report verification results.", prompt)
        self.assertIn("- Report unresolved issues or deviations.", prompt)

    def test_unknown_task_id_raises(self):
        with self.assertRaises(cs.ChangeSpecError):
            cs.build_task_prompt(make_spec(), "task-999")

    def test_empty_optional_lists_render_placeholder(self):
        spec = make_spec(
            non_goals=[],
            requirements=[],
            tasks=[
                make_task(
                    requirement_ids=[], allowed_paths=[], forbidden_paths=[], verification_commands=[]
                )
            ],
        )
        prompt = cs.build_task_prompt(spec, "task-001")
        self.assertIn("Non-Goals\n(none)", prompt)
        self.assertIn("Requirements\n(none)", prompt)
        self.assertIn("Allowed paths:\n(none)", prompt)
        self.assertIn("Forbidden paths (take precedence over allowed paths above):\n(none)", prompt)
        self.assertIn("Verification\n(none)", prompt)

    def test_no_correction_appendix_by_default(self):
        prompt = cs.build_task_prompt(make_spec(), "task-001")
        self.assertNotIn("Correction Pass", prompt)

    def test_correction_appendix_included_when_correction_given(self):
        prompt = cs.build_task_prompt(
            make_spec(),
            "task-001",
            correction="Fix the off-by-one error.",
            previous_result="Added retry logic.",
        )
        self.assertIn(
            "Correction Pass\n\nPrevious executor result:\nAdded retry logic.\n\n"
            "Orchestrator review:\nFix the off-by-one error.",
            prompt,
        )
        self.assertIn("Re-run the original verification commands.", prompt)
        # The appendix must come after the base prompt's final-report section.
        self.assertLess(prompt.index("Required Final Report"), prompt.index("Correction Pass"))

    def test_correction_appendix_uses_placeholder_when_no_previous_result(self):
        prompt = cs.build_task_prompt(make_spec(), "task-001", correction="Fix it.")
        self.assertIn("Previous executor result:\n(no previous result available)", prompt)

    def test_rendered_prompt_never_matches_classifier_ticket_regex(self):
        # PRD section 21 (REVIEW FIX): lowercase task/req IDs must never trip
        # classify_prompt's uppercase ticket-reference regex, regardless of
        # what else ends up in the rendered prompt.
        spec = make_spec(
            goal="Retry transient command-execution failures.",
            tasks=[make_task(instructions=["Implement retry classification.", "Fix the flaky test."])],
        )
        prompt = cs.build_task_prompt(spec, "task-001")
        self.assertIsNone(TICKET_REF_RE.search(prompt))


# --------------------------------------------------------------------------
# Task 4: run_change_task_pipeline (PRD section 16) -- mocked pipeline tests
# --------------------------------------------------------------------------


def make_delegation_result(**overrides) -> pipeline.DelegationResult:
    defaults = dict(
        result="Implemented the retry classification.",
        usage={"input_tokens": 10, "output_tokens": 20},
        cost_usd=0.05,
        terminal_reason="end_turn",
        is_error=False,
        classification={"name": "medium", "task_type": "code_edit"},
        model="deepseek-v4-pro[1m]",
        effort="max",
        permission_mode="bypassPermissions",
        mcp_mode="all",
        task_type="code_edit",
    )
    defaults.update(overrides)
    return pipeline.DelegationResult(**defaults)


class RunChangeTaskPipelineTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.project_root = Path(self._tmpdir.name)
        self.spec = make_spec(
            tasks=[
                make_task(id="task-001", requirement_ids=["req-001"], depends_on=[]),
                make_task(
                    id="task-002",
                    title="Second task",
                    requirement_ids=["req-001"],
                    depends_on=["task-001"],
                ),
            ]
        )
        cs.save_change_spec(self.project_root, self.spec)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_pipeline_called_with_rendered_task_prompt(self):
        with mock.patch(
            "pipeline.run_delegation_pipeline", return_value=make_delegation_result()
        ) as mock_run:
            pipeline.run_change_task_pipeline(
                project_root=str(self.project_root),
                change_id=self.spec.change_id,
                task_id="task-001",
            )
        mock_run.assert_called_once()
        prompt_arg = mock_run.call_args[0][0]
        self.assertEqual(prompt_arg, cs.build_task_prompt(self.spec, "task-001"))
        self.assertEqual(mock_run.call_args[1], {})

    def test_returned_delegation_result_is_unchanged_object(self):
        fake_result = make_delegation_result()
        with mock.patch("pipeline.run_delegation_pipeline", return_value=fake_result):
            out = pipeline.run_change_task_pipeline(
                project_root=str(self.project_root),
                change_id=self.spec.change_id,
                task_id="task-001",
            )
        self.assertIs(out, fake_result)

    def test_successful_delegation_marks_task_delegated(self):
        with mock.patch(
            "pipeline.run_delegation_pipeline", return_value=make_delegation_result(is_error=False)
        ):
            pipeline.run_change_task_pipeline(
                project_root=str(self.project_root),
                change_id=self.spec.change_id,
                task_id="task-001",
            )
        reloaded = cs.load_change_spec(self.project_root, self.spec.change_id)
        task = next(t for t in reloaded.tasks if t.id == "task-001")
        self.assertEqual(task.status, "delegated")

    def test_failed_delegation_marks_task_failed(self):
        with mock.patch(
            "pipeline.run_delegation_pipeline",
            return_value=make_delegation_result(is_error=True, terminal_reason="error"),
        ):
            pipeline.run_change_task_pipeline(
                project_root=str(self.project_root),
                change_id=self.spec.change_id,
                task_id="task-001",
            )
        reloaded = cs.load_change_spec(self.project_root, self.spec.change_id)
        task = next(t for t in reloaded.tasks if t.id == "task-001")
        self.assertEqual(task.status, "failed")

    def test_run_record_persisted_with_expected_fields(self):
        fake_result = make_delegation_result()
        with mock.patch("pipeline.run_delegation_pipeline", return_value=fake_result):
            pipeline.run_change_task_pipeline(
                project_root=str(self.project_root),
                change_id=self.spec.change_id,
                task_id="task-001",
            )
        runs_dir = cs._runs_dir(self.project_root, self.spec.change_id)
        run_files = list(runs_dir.glob("run-*.json"))
        self.assertEqual(len(run_files), 1)
        record = json.loads(run_files[0].read_text(encoding="utf-8"))
        self.assertEqual(record["run_id"], "run-0001")
        self.assertEqual(record["change_id"], self.spec.change_id)
        self.assertEqual(record["task_id"], "task-001")
        self.assertIsNone(record["correction"])
        self.assertEqual(record["executor"], "claude-code")
        self.assertEqual(record["model"], fake_result.model)
        self.assertEqual(record["is_error"], False)
        self.assertEqual(record["result"], fake_result.result)
        self.assertEqual(record["usage"], fake_result.usage)
        self.assertEqual(record["cost_usd"], fake_result.cost_usd)

    def test_unready_task_raises_and_pipeline_not_invoked(self):
        # task-002 depends on task-001, which is still pending (not verified).
        with mock.patch("pipeline.run_delegation_pipeline") as mock_run:
            with self.assertRaises(cs.ChangeSpecError):
                pipeline.run_change_task_pipeline(
                    project_root=str(self.project_root),
                    change_id=self.spec.change_id,
                    task_id="task-002",
                )
        mock_run.assert_not_called()
        runs_dir = cs._runs_dir(self.project_root, self.spec.change_id)
        self.assertFalse(runs_dir.exists())

    def test_unknown_task_id_raises_and_pipeline_not_invoked(self):
        with mock.patch("pipeline.run_delegation_pipeline") as mock_run:
            with self.assertRaises(cs.ChangeSpecError):
                pipeline.run_change_task_pipeline(
                    project_root=str(self.project_root),
                    change_id=self.spec.change_id,
                    task_id="task-999",
                )
        mock_run.assert_not_called()

    def test_correction_pass_includes_previous_result_and_correction_text(self):
        # Simulate a prior rejected attempt: one run record on file, task
        # status moved to "failed" (as record_task_review would do).
        cs.append_run_record(
            self.project_root,
            self.spec.change_id,
            {"task_id": "task-001", "result": "First attempt result."},
        )
        reloaded = cs.load_change_spec(self.project_root, self.spec.change_id)
        for t in reloaded.tasks:
            if t.id == "task-001":
                t.status = "failed"
        cs.save_change_spec(self.project_root, reloaded)

        with mock.patch(
            "pipeline.run_delegation_pipeline", return_value=make_delegation_result()
        ) as mock_run:
            pipeline.run_change_task_pipeline(
                project_root=str(self.project_root),
                change_id=self.spec.change_id,
                task_id="task-001",
                correction="Restrict retries to transient errors only.",
            )

        prompt_arg = mock_run.call_args[0][0]
        self.assertIn("First attempt result.", prompt_arg)
        self.assertIn("Restrict retries to transient errors only.", prompt_arg)
        self.assertIn("Correction Pass", prompt_arg)

        run_files = sorted(cs._runs_dir(self.project_root, self.spec.change_id).glob("run-*.json"))
        self.assertEqual(len(run_files), 2)
        second_record = json.loads(run_files[1].read_text(encoding="utf-8"))
        self.assertEqual(second_record["correction"], "Restrict retries to transient errors only.")

    def test_project_root_defaults_to_cwd(self):
        original_cwd = os.getcwd()
        self.addCleanup(os.chdir, original_cwd)
        os.chdir(self.project_root)

        with mock.patch("pipeline.run_delegation_pipeline", return_value=make_delegation_result()):
            pipeline.run_change_task_pipeline(change_id=self.spec.change_id, task_id="task-001")

        reloaded = cs.load_change_spec(self.project_root, self.spec.change_id)
        task = next(t for t in reloaded.tasks if t.id == "task-001")
        self.assertEqual(task.status, "delegated")

    def test_pipeline_options_forwarded_to_run_delegation_pipeline(self):
        with mock.patch(
            "pipeline.run_delegation_pipeline", return_value=make_delegation_result()
        ) as mock_run:
            pipeline.run_change_task_pipeline(
                project_root=str(self.project_root),
                change_id=self.spec.change_id,
                task_id="task-001",
                model_tier="pro",
                executor="opencode",
            )
        self.assertEqual(mock_run.call_args[1], {"model_tier": "pro", "executor": "opencode"})

    def test_run_delegation_pipeline_signature_unchanged(self):
        # Regression (PRD section 25): the existing prompt-only entry point's
        # call surface must stay unaffected by the change-contract additions.
        sig = inspect.signature(pipeline.run_delegation_pipeline)
        self.assertEqual(
            list(sig.parameters),
            [
                "prompt",
                "model_tier",
                "effort",
                "permission_mode",
                "mcp_mode",
                "context_mode",
                "subagent_mode",
                "output_mode",
                "executor",
            ],
        )


# --------------------------------------------------------------------------
# Review recording (PRD section 18) -- minimal record_task_review, pulled
# forward from task 7 because the TASK-005 CLI `review` subcommand needs it.
# --------------------------------------------------------------------------


class RecordTaskReviewTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.project_root = Path(self._tmpdir.name)
        self.spec = make_spec()
        cs.save_change_spec(self.project_root, self.spec)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_records_status_summary_commands_and_timestamp(self):
        cs.record_task_review(
            self.project_root,
            self.spec.change_id,
            "task-001",
            status="verified",
            summary="Diff limited to invoker.py. Full suite passed.",
            verification_commands=["bash tests/run_tests.sh"],
        )
        reloaded = cs.load_change_spec(self.project_root, self.spec.change_id)
        task = next(t for t in reloaded.tasks if t.id == "task-001")
        self.assertEqual(task.status, "verified")
        self.assertIsNotNone(task.review)
        self.assertEqual(task.review.status, "verified")
        self.assertEqual(task.review.summary, "Diff limited to invoker.py. Full suite passed.")
        self.assertEqual(task.review.verification_commands, ["bash tests/run_tests.sh"])
        self.assertTrue(task.review.reviewed_at)

    def test_returns_updated_spec(self):
        returned = cs.record_task_review(
            self.project_root, self.spec.change_id, "task-001", status="failed", summary="Broke tests."
        )
        task = next(t for t in returned.tasks if t.id == "task-001")
        self.assertEqual(task.status, "failed")

    def test_verification_commands_default_to_empty_list(self):
        cs.record_task_review(
            self.project_root, self.spec.change_id, "task-001", status="blocked", summary="Waiting on task-000."
        )
        reloaded = cs.load_change_spec(self.project_root, self.spec.change_id)
        task = next(t for t in reloaded.tasks if t.id == "task-001")
        self.assertEqual(task.review.verification_commands, [])

    def test_invalid_status_rejected(self):
        with self.assertRaises(cs.ChangeSpecError):
            cs.record_task_review(
                self.project_root, self.spec.change_id, "task-001", status="approved", summary="x"
            )

    def test_unknown_task_id_rejected(self):
        with self.assertRaises(cs.ChangeSpecError):
            cs.record_task_review(
                self.project_root, self.spec.change_id, "task-999", status="verified", summary="x"
            )

    def test_unknown_change_id_rejected(self):
        with self.assertRaises(cs.ChangeSpecError):
            cs.record_task_review(
                self.project_root, "does-not-exist", "task-001", status="verified", summary="x"
            )

    def test_failed_write_leaves_original_status_intact(self):
        with mock.patch("change_spec.os.replace", side_effect=OSError("simulated disk failure")):
            with self.assertRaises(OSError):
                cs.record_task_review(
                    self.project_root, self.spec.change_id, "task-001", status="verified", summary="x"
                )
        reloaded = cs.load_change_spec(self.project_root, self.spec.change_id)
        task = next(t for t in reloaded.tasks if t.id == "task-001")
        self.assertEqual(task.status, "pending")

    def test_does_not_infer_status_from_summary_text(self):
        # PRD section 18: "Do not infer review status from executor text."
        # A summary discussing failure must not override the explicit status
        # argument the orchestrator passed.
        cs.record_task_review(
            self.project_root,
            self.spec.change_id,
            "task-001",
            status="verified",
            summary="The executor initially reported failed tests but a rerun passed.",
        )
        reloaded = cs.load_change_spec(self.project_root, self.spec.change_id)
        task = next(t for t in reloaded.tasks if t.id == "task-001")
        self.assertEqual(task.status, "verified")

    def test_dependency_unblocked_after_review_verified(self):
        spec = make_spec(
            requirements=[make_requirement(id="req-001")],
            tasks=[
                make_task(id="task-001", requirement_ids=["req-001"], status="delegated", depends_on=[]),
                make_task(id="task-002", requirement_ids=["req-001"], depends_on=["task-001"]),
            ],
        )
        cs.save_change_spec(self.project_root, spec)

        blocked, reasons = cs.get_task_readiness(spec, "task-002")
        self.assertFalse(blocked)
        self.assertTrue(any("task-001" in r for r in reasons))

        cs.record_task_review(
            self.project_root, spec.change_id, "task-001", status="verified", summary="Looks good."
        )
        reloaded = cs.load_change_spec(self.project_root, spec.change_id)
        ready, reasons = cs.get_task_readiness(reloaded, "task-002")
        self.assertTrue(ready)
        self.assertEqual(reasons, [])


if __name__ == "__main__":
    unittest.main()
