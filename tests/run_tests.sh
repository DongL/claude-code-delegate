#!/usr/bin/env bash
# Test runner for claude-code-delegate scripts.
# No external packages required — uses fake claude on PATH.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNNER="$SCRIPT_DIR/../scripts/run-claude-code.sh"
COMPACT="$SCRIPT_DIR/../scripts/compact-claude-stream.py"

for f in "$RUNNER" "$COMPACT"; do
  [ -f "$f" ] || { echo "ERROR: $f not found"; exit 1; }
done

SANDBOX=$(mktemp -d)
trap 'rm -rf "$SANDBOX"' EXIT

# Fake claude that records invocation and returns valid JSON.
# CLAUDE_DELEGATOR_TEST_CAPTURE points to a temp file for assertions.
cat > "$SANDBOX/claude" <<'FAKE'
#!/usr/bin/env bash
echo "args:$*" >> "${CLAUDE_DELEGATOR_TEST_CAPTURE:-/dev/null}"
echo "MAX_THINKING_TOKENS:${MAX_THINKING_TOKENS:-}" >> "${CLAUDE_DELEGATOR_TEST_CAPTURE:-/dev/null}"
cat <<'JSONEOF'
{"type":"result","result":"done","usage":{"input_tokens":5,"output_tokens":10}}
JSONEOF
FAKE
chmod +x "$SANDBOX/claude"

export PATH="$SANDBOX:$PATH"

passed=0
failed=0

# ---- helpers ----

# test_case name expected_exit expected_capture_substr [args...]
test_case() {
  local name="$1" expected_exit="$2" expected_capture="$3"
  shift 3
  local capture; capture=$(mktemp "$SANDBOX/cap.XXXX")
  set +e
  CLAUDE_DELEGATOR_TEST_CAPTURE="$capture" "$RUNNER" "$@" >/dev/null 2>/dev/null
  local got_exit=$?
  set -e
  if [ "$got_exit" -ne "$expected_exit" ]; then
    echo "  FAIL  $name (exit $got_exit, expected $expected_exit)"
    failed=$((failed+1))
  elif [ -n "$expected_capture" ] && ! grep -qF -e "$expected_capture" "$capture"; then
    echo "  FAIL  $name (capture missing: $expected_capture)"
    echo "        capture: $(tr '\n' '|' < "$capture")"
    failed=$((failed+1))
  else
    echo "  PASS  $name"
    passed=$((passed+1))
  fi
  rm -f "$capture"
}

# test_exit name expected_exit [args...]
test_exit() {
  local name="$1" expected_exit="$2"
  shift 2
  set +e
  "$RUNNER" "$@" >/dev/null 2>&1
  local got_exit=$?
  set -e
  if [ "$got_exit" -ne "$expected_exit" ]; then
    echo "  FAIL  $name (exit $got_exit, expected $expected_exit)"
    failed=$((failed+1))
  else
    echo "  PASS  $name"
    passed=$((passed+1))
  fi
}

# test_compact name expected_exit expected_out_substr stdin_text
test_compact() {
  local name="$1" expected_exit="$2" expected_out="$3" input="$4"
  local outfile; outfile=$(mktemp "$SANDBOX/cs_out.XXXX")
  set +e
  printf '%s' "$input" | "$COMPACT" > "$outfile" 2>/dev/null
  local rc=$?
  set -e
  if [ "$rc" -ne "$expected_exit" ]; then
    echo "  FAIL  $name (exit $rc, expected $expected_exit)"
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

# ---- run-claude-code.sh tests ----

echo "=== run-claude-code.sh ==="

test_case "default pro model" 0 "--model deepseek-v4-pro[1m]" "test prompt"

test_case "default acceptEdits" 0 "--permission-mode acceptEdits" "test prompt"

test_case "--flash flag" 0 "--model deepseek-v4-flash[1m]" --flash "test prompt"

test_case "--pro flag" 0 "--model deepseek-v4-pro[1m]" --pro "test prompt"

CLAUDE_DELEGATOR_MODEL="claude-sonnet-4-6" \
  test_case "CLAUDE_DELEGATOR_MODEL override" 0 "--model claude-sonnet-4-6" "test prompt"

CLAUDE_DELEGATOR_EFFORT="medium" \
  test_case "CLAUDE_DELEGATOR_EFFORT override" 0 "--effort medium" "test prompt"

CLAUDE_DELEGATOR_PERMISSION_MODE="bypassPermissions" \
  test_case "CLAUDE_DELEGATOR_PERMISSION_MODE override" 0 "--permission-mode bypassPermissions" "test prompt"

test_case "--bypass flag" 0 "--permission-mode bypassPermissions" --bypass "test prompt"

# Quiet mode (default) writes JSON to temp file, pipes through compact script
test_case "quiet mode output-format json" 0 "--output-format json" "test prompt"

# Stream mode adds verbose + stream-json + include-partial-messages
test_case "stream mode --verbose" 0 "--verbose" --stream "test prompt"
test_case "stream mode stream-json" 0 "--output-format stream-json" --stream "test prompt"
test_case "stream mode include-partial" 0 "--include-partial-messages" --stream "test prompt"

CLAUDE_DELEGATOR_OUTPUT_MODE="invalid" \
  test_exit "invalid output mode" 2 "test prompt"

CLAUDE_DELEGATOR_THINKING_TOKENS="0" \
  test_case "CLAUDE_DELEGATOR_THINKING_TOKENS export" 0 "MAX_THINKING_TOKENS:0" "test prompt"

test_exit "no prompt exits 2" 2

# Test that --stream flag does NOT imply --quiet output format
test_case "stream flag adds verbose" 0 "--verbose" --stream "test prompt"

# Env override: CLAUDE_DELEGATOR_OUTPUT_MODE=stream
CLAUDE_DELEGATOR_OUTPUT_MODE="stream" \
  test_case "env output_mode stream" 0 "--verbose" "test prompt"

# ---- compact-claude-stream.py tests ----

echo ""
echo "=== compact-claude-stream.py ==="

test_compact "final JSON object" 0 "hello" \
  '{"type":"result","result":"hello"}'

test_compact "newline-delimited stream events" 0 "model: test-model" \
  '{"type":"system","subtype":"init","model":"test-model"}
{"type":"result","result":"ok"}'

test_compact "malformed lines produce warnings" 0 "Stream Warnings" \
  'not json
{"type":"result","result":"ok"}'

test_compact "error result exit code 1" 1 "failed" \
  '{"type":"result","result":"failed","is_error":true}'

test_compact "usage in result" 0 "input_tokens=5, output_tokens=10" \
  '{"type":"result","result":"ok","usage":{"input_tokens":5,"output_tokens":10}}'

test_compact "cost in result" 0 "total_cost_usd=0.001500" \
  '{"type":"result","result":"ok","usage":{"input_tokens":5},"total_cost_usd":0.0015}'

test_compact "terminal_reason" 0 "terminal_reason=completed" \
  '{"type":"result","result":"ok","terminal_reason":"completed"}'

test_compact "empty input exit 1" 1 "" ""

# ---- jira-safe-text.py tests ----

echo ""
echo "=== jira-safe-text.py ==="

JIRA_SAFE="$SCRIPT_DIR/../scripts/jira-safe-text.py"
[ -f "$JIRA_SAFE" ] || { echo "ERROR: $JIRA_SAFE not found"; exit 1; }

# test_jira name input_text expected_output_substr
test_jira() {
  local name="$1" input="$2" expected="$3"
  local got; got=$(printf '%s' "$input" | python3 "$JIRA_SAFE" 2>/dev/null)
  if ! echo "$got" | grep -qF -e "$expected"; then
    echo "  FAIL  $name (missing: $expected)"
    echo "        got: $got"
    failed=$((failed+1))
  else
    echo "  PASS  $name"
    passed=$((passed+1))
  fi
}

# test_jira_exact name input_text expected_full_output
test_jira_exact() {
  local name="$1" input="$2" expected="$3"
  local got; got=$(printf '%s' "$input" | python3 "$JIRA_SAFE" 2>/dev/null)
  if [ "$got" != "$expected" ]; then
    echo "  FAIL  $name"
    echo "        expected: $expected"
    echo "        got:      $got"
    failed=$((failed+1))
  else
    echo "  PASS  $name"
    passed=$((passed+1))
  fi
}

test_jira_exact "bold stripped" "hello **world** here" "hello world here"

test_jira_exact "italic star stripped" "this is *important* now" "this is important now"

test_jira_exact "italic underscore stripped" "this is _important_ now" "this is important now"

test_jira_exact "inline code stripped" "call \`foo()\` function" "call foo() function"

test_jira_exact "link text preserved" "see [the docs](https://example.com) for help" "see the docs for help"

test_jira_exact "image alt preserved" "diagram ![architecture](img/arch.png) shows flow" "diagram architecture shows flow"

test_jira_exact "strikethrough stripped" "this is ~~wrong~~ correct" "this is wrong correct"

test_jira_exact "heading markers stripped" "# Main Title" "Main Title"

test_jira_exact "h3 stripped" "### Subsection" "Subsection"

test_jira_exact "unchecked task" "- [ ] add tests" "- add tests"

test_jira_exact "checked task" "- [x] write docs" "- (done) write docs"

test_jira_exact "indented unchecked" "  - [ ] nested task" "  - nested task"

test_jira "fenced code block preserved content" '```python
print("hello")
print("world")
```' 'print("hello")'

test_jira_exact "blockquote stripped" "> This is a quote" "This is a quote"

test_jira_exact "bold with __" "__underlined__ text" "underlined text"

test_jira "bullet list preserved" "- item one\n- item two" "- item one"

test_jira "multi-line comprehensive" \
  "**Bold intro** with *emphasis* and \`code\`.\n\nSee [link](http://x.com).\n\n- [x] Done thing\n- [ ] Todo thing\n\n## Notes\n\nPlain text here." \
  "Plain text here."

# ---- summary ----

echo ""
echo "---"
echo "Result: $passed passed, $failed failed"

if [ "$failed" -gt 0 ]; then
  exit 1
fi
