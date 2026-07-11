#!/usr/bin/env bash
# Tests for scripts/change-spec.py (PRD docs/prd/change-contracts.md section 20
# management CLI). No external packages required.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CHANGE_SPEC_CLI="$SCRIPT_DIR/../scripts/change-spec.py"

[ -f "$CHANGE_SPEC_CLI" ] || { echo "ERROR: $CHANGE_SPEC_CLI not found"; exit 1; }

SANDBOX=$(mktemp -d)
trap 'rm -rf "$SANDBOX"' EXIT

PROJECT_ROOT="$SANDBOX/project"
mkdir -p "$PROJECT_ROOT"

passed=0
failed=0

# ---- helpers ----

# make_spec change_id [task_status]
make_spec() {
  local change_id="$1" task_status="${2:-pending}"
  python3 -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR/../scripts')
from pathlib import Path
from change_spec import ChangeSpec, ChangeRequirement, ChangeTask, save_change_spec

spec = ChangeSpec(
    schema_version=1,
    change_id='$change_id',
    title='Test change',
    status='active',
    goal='Exercise the change-spec.py CLI.',
    non_goals=['Do not add a dependency.'],
    requirements=[ChangeRequirement(id='req-001', text='Do the thing.')],
    tasks=[
        ChangeTask(
            id='task-001',
            title='Do the thing',
            instructions=['Do it.'],
            requirement_ids=['req-001'],
            status='$task_status',
        )
    ],
    created_at='2026-07-10T00:00:00Z',
    updated_at='2026-07-10T00:00:00Z',
)
save_change_spec(Path('$PROJECT_ROOT'), spec)
"
}

# make_invalid_spec change_id -- schema_version=2 bypasses validate_change_spec
# (save_change_spec never validates -- see PRD section 13).
make_invalid_spec() {
  local change_id="$1"
  python3 -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR/../scripts')
from pathlib import Path
from change_spec import ChangeSpec, save_change_spec

spec = ChangeSpec(
    schema_version=2,
    change_id='$change_id',
    title='Broken change',
    status='active',
    goal='Broken.',
    non_goals=[],
    requirements=[],
    tasks=[],
    created_at='2026-07-10T00:00:00Z',
    updated_at='2026-07-10T00:00:00Z',
)
save_change_spec(Path('$PROJECT_ROOT'), spec)
"
}

# run_cli name expected_exit expected_stdout_substr [args...]
run_cli() {
  local name="$1" expected_exit="$2" expected_out="$3"
  shift 3
  local outfile; outfile=$(mktemp "$SANDBOX/out.XXXX")
  set +e
  python3 "$CHANGE_SPEC_CLI" "$@" > "$outfile" 2>&1
  local rc=$?
  set -e
  if [ "$rc" -ne "$expected_exit" ]; then
    echo "  FAIL  $name (exit $rc, expected $expected_exit)"
    echo "        output: $(cat "$outfile")"
    failed=$((failed+1))
  elif [ -n "$expected_out" ] && ! grep -qF -e "$expected_out" "$outfile"; then
    echo "  FAIL  $name (output missing: $expected_out)"
    echo "        output: $(cat "$outfile")"
    failed=$((failed+1))
  else
    echo "  PASS  $name"
    passed=$((passed+1))
  fi
  rm -f "$outfile"
}

# ---- validate ----

echo "=== change-spec.py validate ==="

make_spec "valid-change" pending
run_cli "validate exits 0 for valid contract" 0 "is valid" \
  validate valid-change --project-root "$PROJECT_ROOT"

make_invalid_spec "broken-change"
run_cli "validate exits non-zero for invalid contract" 1 "schema_version" \
  validate broken-change --project-root "$PROJECT_ROOT"

run_cli "validate unknown change_id exits non-zero" 1 "error" \
  validate does-not-exist --project-root "$PROJECT_ROOT"

# ---- show ----

echo ""
echo "=== change-spec.py show ==="

run_cli "show prints JSON contract" 0 '"change_id": "valid-change"' \
  show valid-change --project-root "$PROJECT_ROOT"

run_cli "show unknown change_id exits non-zero" 1 "error" \
  show does-not-exist --project-root "$PROJECT_ROOT"

# ---- list ----

echo ""
echo "=== change-spec.py list ==="

run_cli "list shows saved change" 0 "valid-change" \
  list --project-root "$PROJECT_ROOT"

run_cli "list shows per-status task counts" 0 "pending=1" \
  list --project-root "$PROJECT_ROOT"

EMPTY_ROOT="$SANDBOX/empty_project"
mkdir -p "$EMPTY_ROOT"
run_cli "list with no changes exits 0" 0 "no change contracts found" \
  list --project-root "$EMPTY_ROOT"

# ---- review ----

echo ""
echo "=== change-spec.py review ==="

make_spec "review-change" pending
run_cli "review records verified status" 0 "verified" \
  review review-change task-001 \
    --status verified --summary "Focused and full tests passed." \
    --project-root "$PROJECT_ROOT"

if python3 -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR/../scripts')
from pathlib import Path
from change_spec import load_change_spec
spec = load_change_spec(Path('$PROJECT_ROOT'), 'review-change')
task = next(t for t in spec.tasks if t.id == 'task-001')
assert task.status == 'verified', task.status
assert task.review is not None
assert task.review.status == 'verified'
assert task.review.summary == 'Focused and full tests passed.'
assert task.review.reviewed_at
print('review_persisted_ok')
" 2>&1 | grep -q "review_persisted_ok"; then
  echo "  PASS  review persists status/summary/reviewed_at to change.json"
  passed=$((passed+1))
else
  echo "  FAIL  review persists status/summary/reviewed_at to change.json"
  failed=$((failed+1))
fi

make_spec "review-commands-change" pending
run_cli "review stores verification_commands actually checked" 0 "verified" \
  review review-commands-change task-001 \
    --status verified --summary "Ran the suite." \
    --verification-commands "bash tests/run_tests.sh" "python3 -m unittest" \
    --project-root "$PROJECT_ROOT"

if python3 -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR/../scripts')
from pathlib import Path
from change_spec import load_change_spec
spec = load_change_spec(Path('$PROJECT_ROOT'), 'review-commands-change')
task = next(t for t in spec.tasks if t.id == 'task-001')
assert task.review.verification_commands == ['bash tests/run_tests.sh', 'python3 -m unittest'], task.review.verification_commands
print('verification_commands_ok')
" 2>&1 | grep -q "verification_commands_ok"; then
  echo "  PASS  review --verification-commands accepts multiple values"
  passed=$((passed+1))
else
  echo "  FAIL  review --verification-commands accepts multiple values"
  failed=$((failed+1))
fi

run_cli "review rejects invalid status (argparse choices)" 2 "" \
  review review-change task-001 --status bogus --summary "x" --project-root "$PROJECT_ROOT"

run_cli "review unknown task_id produces useful error" 1 "unknown task id" \
  review review-change task-999 --status verified --summary "x" --project-root "$PROJECT_ROOT"

run_cli "review unknown change_id produces useful error" 1 "error" \
  review does-not-exist task-001 --status verified --summary "x" --project-root "$PROJECT_ROOT"

run_cli "review does not infer status from summary text" 0 "" \
  review review-change task-001 \
    --status verified --summary "The tests initially failed but a rerun passed." \
    --project-root "$PROJECT_ROOT"

if python3 -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR/../scripts')
from pathlib import Path
from change_spec import load_change_spec
spec = load_change_spec(Path('$PROJECT_ROOT'), 'review-change')
task = next(t for t in spec.tasks if t.id == 'task-001')
assert task.status == 'verified', task.status
print('status_not_inferred_ok')
" 2>&1 | grep -q "status_not_inferred_ok"; then
  echo "  PASS  review status is exactly what was passed, never inferred from text"
  passed=$((passed+1))
else
  echo "  FAIL  review status is exactly what was passed, never inferred from text"
  failed=$((failed+1))
fi

# ---- --project-root defaults to cwd ----

echo ""
echo "=== change-spec.py --project-root defaults to cwd ==="

CWD_ROOT="$SANDBOX/cwd_project"
mkdir -p "$CWD_ROOT"
python3 -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR/../scripts')
from pathlib import Path
from change_spec import ChangeSpec, ChangeRequirement, ChangeTask, save_change_spec
spec = ChangeSpec(
    schema_version=1, change_id='cwd-change', title='CWD change', status='active',
    goal='g', non_goals=[], requirements=[ChangeRequirement(id='req-001', text='t')],
    tasks=[ChangeTask(id='task-001', title='t', instructions=['i'], requirement_ids=['req-001'])],
    created_at='2026-07-10T00:00:00Z', updated_at='2026-07-10T00:00:00Z',
)
save_change_spec(Path('$CWD_ROOT'), spec)
"
outfile=$(mktemp "$SANDBOX/out.XXXX")
set +e
( cd "$CWD_ROOT" && python3 "$CHANGE_SPEC_CLI" validate cwd-change ) > "$outfile" 2>&1
rc=$?
set -e
if [ "$rc" -eq 0 ] && grep -qF -e "is valid" "$outfile"; then
  echo "  PASS  --project-root defaults to cwd when omitted"
  passed=$((passed+1))
else
  echo "  FAIL  --project-root defaults to cwd when omitted"
  echo "        output: $(cat "$outfile")"
  failed=$((failed+1))
fi
rm -f "$outfile"

# ---- summary ----

echo ""
echo "---"
echo "Result: $passed passed, $failed failed"

if [ "$failed" -gt 0 ]; then
  exit 1
fi
