#!/usr/bin/env bash
# Smoke tests for claude-code-delegate.
# Requires CLAUDE_DELEGATE_SMOKE_TEST=1 to run (opt-in guard).
# These tests touch live external services (Jira, Claude provider).
set -euo pipefail

if [ "${CLAUDE_DELEGATE_SMOKE_TEST:-0}" != "1" ]; then
  echo "Smoke tests require CLAUDE_DELEGATE_SMOKE_TEST=1"
  echo "These tests touch live external services and are not part of default CI."
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNNER="$SCRIPT_DIR/run-claude-code.sh"
PASSED=0
FAILED=0

smoke() {
  local name="$1" desc="$2"
  echo "  SMOKE $name: $desc"
}

echo "=== claude-code-delegate Smoke Tests ==="
echo ""

# S1: Pipeline invocation with local-only delegation
smoke "S1" "Local-only delegation via pipeline"
set +e
OUTPUT=$("$RUNNER" --flash --mcp none "say hello and report the current date" 2>/dev/null)
RC=$?
set -e
if [ "$RC" -eq 0 ] && echo "$OUTPUT" | grep -q "model:"; then
  echo "    PASS (exit=$RC)"
  PASSED=$((PASSED+1))
else
  echo "    FAIL (exit=$RC)"
  FAILED=$((FAILED+1))
fi

echo ""
echo "Smoke Results: $PASSED passed, $FAILED failed"
exit $FAILED
