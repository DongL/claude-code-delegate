#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GATE_SCRIPT="$SCRIPT_DIR/quality-gate.sh"

TAG="${CLAUDE_DELEGATE_RELEASE_TAG:-none}"
COMMIT=$(git rev-parse HEAD 2>/dev/null || echo "unknown")

echo "Release Quality Gate Report"
echo "==========================="
echo ""

# Run the quality gate, capture output and exit code
GATE_OUTPUT=$("$GATE_SCRIPT" 2>&1) || GATE_EXIT=$?
GATE_EXIT=${GATE_EXIT:-0}

if [ "$GATE_EXIT" -eq 0 ]; then
  STATUS="PASS"
else
  STATUS="FAIL"
fi

echo "Gate Status: $STATUS"
echo "Commit: $COMMIT"
echo "Tag: $TAG"
echo "Tests Run: bash tests/run_tests.sh (via quality-gate.sh)"
echo ""
echo "Residual Risk:"
echo "  - External systems (Claude provider, Jira, GitHub) are mocked in default CI"
echo "  - Real external-system smoke tests are manual/pre-release only"
echo "  - Isolated Claude runtime assumes no ~/.claude coupling"
echo ""

echo "Profiling Metadata:"
if [ -n "${CLAUDE_DELEGATE_PROFILE_LOG:-}" ] && [ -f "$CLAUDE_DELEGATE_PROFILE_LOG" ]; then
  python3 "$SCRIPT_DIR/aggregate-profile-log.py" "$CLAUDE_DELEGATE_PROFILE_LOG"
else
  echo "  not available (CLAUDE_DELEGATE_PROFILE_LOG not set or file absent)"
fi
echo ""

if [ "$GATE_EXIT" -ne 0 ]; then
  echo "RELEASE BLOCKED: quality gate failed"
fi

# Report the gate output for diagnostics
echo ""
echo "--- Gate Output ---"
echo "$GATE_OUTPUT"

exit "$GATE_EXIT"
