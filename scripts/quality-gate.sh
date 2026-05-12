#!/usr/bin/env bash
set -euo pipefail

TEST_COMMAND="${CLAUDE_DELEGATE_QUALITY_GATE_TEST_COMMAND:-bash tests/run_tests.sh}"

echo "Quality Gate: claude-code-delegate"
echo "Test Runner: $TEST_COMMAND"
echo ""

eval "$TEST_COMMAND"
