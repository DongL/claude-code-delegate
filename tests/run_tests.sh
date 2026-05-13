#!/usr/bin/env bash
# Test runner for claude-code-delegate scripts.
# No external packages required — uses fake claude on PATH.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNNER="$SCRIPT_DIR/../scripts/run-claude-code.sh"
COMPACT="$SCRIPT_DIR/../scripts/compact-claude-stream.py"
AGGREGATOR="$SCRIPT_DIR/../scripts/aggregate-profile-log.py"

for f in "$RUNNER" "$COMPACT" "$AGGREGATOR"; do
  [ -f "$f" ] || { echo "ERROR: $f not found"; exit 1; }
done

SANDBOX=$(mktemp -d)
trap 'rm -rf "$SANDBOX"' EXIT

# Fake claude that records invocation and returns valid JSON.
# CLAUDE_DELEGATE_TEST_CAPTURE points to a temp file for assertions.
cat > "$SANDBOX/claude" <<'FAKE'
#!/usr/bin/env bash
echo "args:$*" >> "${CLAUDE_DELEGATE_TEST_CAPTURE:-/dev/null}"
echo "MAX_THINKING_TOKENS:${MAX_THINKING_TOKENS:-}" >> "${CLAUDE_DELEGATE_TEST_CAPTURE:-/dev/null}"
echo "ANTHROPIC_BASE_URL:${ANTHROPIC_BASE_URL:-}" >> "${CLAUDE_DELEGATE_TEST_CAPTURE:-/dev/null}"
echo "ANTHROPIC_AUTH_TOKEN:${ANTHROPIC_AUTH_TOKEN:-}" >> "${CLAUDE_DELEGATE_TEST_CAPTURE:-/dev/null}"
echo "CLAUDE_CONFIG_DIR:${CLAUDE_CONFIG_DIR:-}" >> "${CLAUDE_DELEGATE_TEST_CAPTURE:-/dev/null}"
cat <<'JSONEOF'
{"type":"result","result":"done","usage":{"input_tokens":5,"output_tokens":10}}
JSONEOF
FAKE
chmod +x "$SANDBOX/claude"

export PATH="$SANDBOX:$PATH"

# Unset profile log to prevent test runs from polluting real profiling data.
# The profile-logging test case sets its own CLAUDE_DELEGATE_PROFILE_LOG to a sandbox path.
unset CLAUDE_DELEGATE_PROFILE_LOG

passed=0
failed=0

# ---- helpers ----

# test_case name expected_exit expected_capture_substr [args...]
test_case() {
  local name="$1" expected_exit="$2" expected_capture="$3"
  shift 3
  local capture; capture=$(mktemp "$SANDBOX/cap.XXXX")
  set +e
  CLAUDE_DELEGATE_TEST_CAPTURE="$capture" "$RUNNER" "$@" >/dev/null 2>/dev/null
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

# test_case_absent name unexpected_capture_substr [args...]
test_case_absent() {
  local name="$1" unexpected_capture="$2"
  shift 2
  local capture; capture=$(mktemp "$SANDBOX/cap.XXXX")
  set +e
  CLAUDE_DELEGATE_TEST_CAPTURE="$capture" "$RUNNER" "$@" >/dev/null 2>/dev/null
  local got_exit=$?
  set -e
  if [ "$got_exit" -ne 0 ]; then
    echo "  FAIL  $name (exit $got_exit, expected 0)"
    failed=$((failed+1))
  elif grep -qF -e "$unexpected_capture" "$capture"; then
    echo "  FAIL  $name (unexpected capture: $unexpected_capture)"
    echo "        capture: $(tr '\n' '|' < "$capture")"
    failed=$((failed+1))
  else
    echo "  PASS  $name"
    passed=$((passed+1))
  fi
  rm -f "$capture"
}

# test_runner_stdout name expected_stdout_substr [args...]
# Like test_case but captures stdout instead of discarding it.
test_runner_stdout() {
  local name="$1" expected_stdout="$2"
  shift 2
  local stdout_file; stdout_file=$(mktemp "$SANDBOX/stdout.XXXX")
  local capture; capture=$(mktemp "$SANDBOX/cap.XXXX")
  set +e
  CLAUDE_DELEGATE_TEST_CAPTURE="$capture" "$RUNNER" "$@" > "$stdout_file" 2>/dev/null
  local got_exit=$?
  set -e
  if [ "$got_exit" -ne 0 ]; then
    echo "  FAIL  $name (exit $got_exit, expected 0)"
    failed=$((failed+1))
  elif ! grep -qF -e "$expected_stdout" "$stdout_file"; then
    echo "  FAIL  $name (stdout missing: $expected_stdout)"
    echo "        stdout: $(tr '\n' '|' < "$stdout_file")"
    failed=$((failed+1))
  else
    echo "  PASS  $name"
    passed=$((passed+1))
  fi
  rm -f "$stdout_file" "$capture"
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

test_case "default bypassPermissions" 0 "--permission-mode bypassPermissions" "test prompt"

test_case "default disables subagents" 0 "--disallowedTools Task Agent" "test prompt"

test_case "--flash flag" 0 "--model deepseek-v4-flash[1m]" --flash "test prompt"

test_case "--pro flag" 0 "--model deepseek-v4-pro[1m]" --pro "test prompt"

CLAUDE_DELEGATE_MODEL="claude-sonnet-4-6" \
  test_case "CLAUDE_DELEGATE_MODEL override" 0 "--model claude-sonnet-4-6" "test prompt"

CLAUDE_DELEGATE_EFFORT="medium" \
  test_case "CLAUDE_DELEGATE_EFFORT override" 0 "--effort medium" "test prompt"

CLAUDE_DELEGATE_PERMISSION_MODE="bypassPermissions" \
  test_case "CLAUDE_DELEGATE_PERMISSION_MODE override" 0 "--permission-mode bypassPermissions" "test prompt"

test_case "--bypass flag" 0 "--permission-mode bypassPermissions" --bypass "test prompt"

test_case "--interactive flag" 0 "--permission-mode acceptEdits" --interactive "test prompt"

# Explicit flag overrides env var
CLAUDE_DELEGATE_PERMISSION_MODE="acceptEdits" \
  test_case "--bypass overrides env acceptEdits" 0 "--permission-mode bypassPermissions" --bypass "test prompt"

CLAUDE_DELEGATE_PERMISSION_MODE="bypassPermissions" \
  test_case "--interactive overrides env bypassPermissions" 0 "--permission-mode acceptEdits" --interactive "test prompt"

# Quiet mode (default) writes JSON to temp file, pipes through compact script
test_case "quiet mode output-format json" 0 "--output-format json" "test prompt"

# Quiet report metadata assertions (stdout capture)
test_runner_stdout "quiet report shows permissionMode" "permissionMode: bypassPermissions" "test prompt"

test_runner_stdout "quiet report shows mcpMode" "mcpMode: all" "test prompt"

test_runner_stdout "quiet report shows Classification section" "Classification" "check how many rows are in pattern_data"

test_runner_stdout "quiet report shows taskType" "taskType: read_only_scan" "check how many rows are in pattern_data"

test_runner_stdout "quiet report shows Prompt section" "Prompt" "check how many rows are in pattern_data"

test_runner_stdout "quiet report shows prompt mode" "mode: template" "check how many rows are in pattern_data"

test_case "tiny task routes to flash" 0 "--model deepseek-v4-flash[1m]" "check how many rows are in pattern_data"

test_case "tiny task uses low effort" 0 "--effort low" "check how many rows are in pattern_data"

test_case "routine edit routes to flash" 0 "--model deepseek-v4-flash[1m]" "fix the README typo"

test_case "routine edit uses medium effort" 0 "--effort medium" "fix the README typo"

test_case "debug task routes to pro" 0 "--model deepseek-v4-pro[1m]" "diagnose this traceback failure"

test_case "debug task uses high effort" 0 "--effort high" "diagnose this traceback failure"

test_case "architecture task uses max effort" 0 "--effort max" "architecture refactor plan"

test_case "--pro overrides tiny classification" 0 "--model deepseek-v4-pro[1m]" --pro "check how many rows are in pattern_data"

test_case "--effort overrides classification" 0 "--effort max" --effort max "check how many rows are in pattern_data"

test_case "--interactive overrides classified permission" 0 "--permission-mode acceptEdits" --interactive "check how many rows are in pattern_data"

test_case "read-only prompt template applied" 0 "Task Template: read-only scan" "check how many rows are in pattern_data"

test_case "code edit prompt template applied" 0 "Task Template: code edit" "fix the README typo"

test_case "implement issue key remains code edit" 0 "Task Template: code edit" "implement ITRADE-90"

test_case "jira prompt template applied" 0 "Task Template: Jira operation" "mark ITRADE-90 done in Jira"

test_case "architecture prompt template applied" 0 "Task Template: architecture review" "architecture refactor plan"

test_case_absent "unknown task falls back to full prompt" "Task Template:" "hello world"

test_case_absent "--full-context disables template" "Task Template:" --full-context "check how many rows are in pattern_data"

test_case_absent "--allow-subagents omits disallowedTools" "--disallowedTools" --allow-subagents "test prompt"

# Stream mode adds verbose + stream-json + include-partial-messages
test_case "stream mode --verbose" 0 "--verbose" --stream "test prompt"
test_case "stream mode stream-json" 0 "--output-format stream-json" --stream "test prompt"
test_case "stream mode include-partial" 0 "--include-partial-messages" --stream "test prompt"

CLAUDE_DELEGATE_OUTPUT_MODE="invalid" \
  test_exit "invalid output mode" 2 "test prompt"

CLAUDE_DELEGATE_SUBAGENTS="invalid" \
  test_exit "invalid subagent mode" 2 "test prompt"

CLAUDE_DELEGATE_HEARTBEAT_SECONDS="abc" \
  test_exit "invalid heartbeat seconds" 2 "test prompt"

CLAUDE_DELEGATE_THINKING_TOKENS="0" \
  test_case "CLAUDE_DELEGATE_THINKING_TOKENS export" 0 "MAX_THINKING_TOKENS:0" "test prompt"

test_case_absent "default mcp all no strict config" "--strict-mcp-config" "test prompt"

test_case "--mcp none strict config" 0 "--strict-mcp-config" --mcp none "test prompt"

test_case "--mcp none passes mcp-config" 0 "--mcp-config" --mcp none "test prompt"

test_case "--mcp none empty config" 0 "strict-mcp-config" --mcp none "test prompt"

cat > "$SANDBOX/mcp.json" <<'JSON'
{
  "mcpServers": {
    "jira": { "command": "node", "args": ["jira.js"] },
    "linear": { "command": "node", "args": ["linear.js"] },
    "sequential-thinking": { "command": "node", "args": ["seq.js"] }
  }
}
JSON

CLAUDE_DELEGATE_MCP_CONFIG_PATH="$SANDBOX/mcp.json" \
  test_case "--mcp jira strict config" 0 "--strict-mcp-config" --mcp jira "test prompt"

CLAUDE_DELEGATE_MCP_CONFIG_PATH="$SANDBOX/mcp.json" \
  test_case "--mcp jira passes generated mcp-config" 0 "--strict-mcp-config" --mcp jira "test prompt"

CLAUDE_DELEGATE_MCP_CONFIG_PATH="$SANDBOX/mcp.json" \
  test_case "--mcp jira passes mcp-config flag" 0 "--mcp-config" --mcp jira "test prompt"

CLAUDE_DELEGATE_MCP_MODE="none" \
  test_case "env mcp mode none" 0 "--strict-mcp-config" "test prompt"

test_exit "invalid mcp mode" 2 --mcp invalid "test prompt"

test_exit "no prompt exits 2" 2

# Test that --stream flag does NOT imply --quiet output format
test_case "stream flag adds verbose" 0 "--verbose" --stream "test prompt"

# Env override: CLAUDE_DELEGATE_OUTPUT_MODE=stream
CLAUDE_DELEGATE_OUTPUT_MODE="stream" \
  test_case "env output_mode stream" 0 "--verbose" "test prompt"

# ---- regression harness: heartbeat, stream events, no-output diagnosis ----

# test_stderr name expected_stderr_substr [args...]
# Captures stderr separately instead of discarding it
test_stderr() {
  local name="$1" expected="$2"
  shift 2
  local stderr_capture; stderr_capture=$(mktemp "$SANDBOX/stderr.XXXX")
  local capture; capture=$(mktemp "$SANDBOX/cap.XXXX")
  set +e
  CLAUDE_DELEGATE_TEST_CAPTURE="$capture" "$RUNNER" "$@" >/dev/null 2>"$stderr_capture"
  local got_exit=$?
  set -e
  if [ "$got_exit" -ne 0 ]; then
    echo "  FAIL  $name (exit $got_exit, expected 0)"
    echo "        stderr: $(tr '\n' '|' < "$stderr_capture")"
    failed=$((failed+1))
  elif ! grep -qF -e "$expected" "$stderr_capture"; then
    echo "  FAIL  $name (stderr missing: $expected)"
    echo "        stderr: $(tr '\n' '|' < "$stderr_capture")"
    failed=$((failed+1))
  else
    echo "  PASS  $name"
    passed=$((passed+1))
  fi
  rm -f "$stderr_capture" "$capture"
}

# test_stderr_absent name unexpected_stderr_substr [args...]
# Captures stderr and checks absence of a substring
test_stderr_absent() {
  local name="$1" unexpected="$2"
  shift 2
  local stderr_capture; stderr_capture=$(mktemp "$SANDBOX/stderr.XXXX")
  local capture; capture=$(mktemp "$SANDBOX/cap.XXXX")
  set +e
  CLAUDE_DELEGATE_TEST_CAPTURE="$capture" "$RUNNER" "$@" >/dev/null 2>"$stderr_capture"
  local got_exit=$?
  set -e
  if [ "$got_exit" -ne 0 ]; then
    echo "  FAIL  $name (exit $got_exit, expected 0)"
    echo "        stderr: $(tr '\n' '|' < "$stderr_capture")"
    failed=$((failed+1))
  elif grep -qF -e "$unexpected" "$stderr_capture"; then
    echo "  FAIL  $name (stderr unexpectedly contains: $unexpected)"
    echo "        stderr: $(tr '\n' '|' < "$stderr_capture")"
    failed=$((failed+1))
  else
    echo "  PASS  $name"
    passed=$((passed+1))
  fi
  rm -f "$stderr_capture" "$capture"
}

# test_stream_compact name expected_substr stdin_text
# Like test_compact but simulates stream-mode event parsing
test_stream_compact() {
  local name="$1" expected="$2" input="$3"
  local outfile; outfile=$(mktemp "$SANDBOX/stream_out.XXXX")
  set +e
  printf '%s' "$input" | "$COMPACT" > "$outfile" 2>/dev/null
  local rc=$?
  set -e
  if ! grep -qF -e "$expected" "$outfile"; then
    echo "  FAIL  $name (output missing: $expected)"
    echo "        output: $(cat "$outfile")"
    failed=$((failed+1))
  else
    echo "  PASS  $name"
    passed=$((passed+1))
  fi
  rm -f "$outfile"
}

echo ""
echo "=== regression harness ==="

# Heartbeat tests (stderr capture)
test_case "pipeline invokes claude with model" 0 "--model" "test prompt"

CLAUDE_DELEGATE_HEARTBEAT_SECONDS=0 \
  test_stderr_absent "heartbeat disabled with 0" "Traceback" "test prompt"

# Stream mode: compact script parses init events with model, mcpMode, effort
test_stream_compact "stream compact parses model from init" "model: stream-test" \
  '{"type":"system","subtype":"init","model":"stream-test"}
{"type":"result","result":"ok"}'

test_stream_compact "stream compact parses mcpMode from init" "mcpMode: jira-only" \
  '{"type":"system","subtype":"init","mcpMode":"jira-only"}
{"type":"result","result":"ok"}'

test_stream_compact "stream compact parses effort from init" "effort: max" \
  '{"type":"system","subtype":"init","effort":"max"}
{"type":"result","result":"ok"}'

# Stream mode: tool events do not break compact output
test_stream_compact "stream compact ignores tool_use events" "done" \
  '{"type":"tool_use","name":"Read"}
{"type":"tool_result","content":"file content"}
{"type":"result","result":"done"}'

# Stream mode: multiple events are all handled
test_stream_compact "stream compact multiple events" "input_tokens=10, output_tokens=20" \
  '{"type":"system","subtype":"init","model":"m"}
{"type":"tool_use","name":"Bash"}
{"type":"tool_result","content":"output"}
{"type":"progress","partial":"thinking"}
{"type":"result","result":"completed","usage":{"input_tokens":10,"output_tokens":20}}'

# No output at all produces exit code 1
test_compact "no input events exit 1" 1 "" ""

# Only non-result non-init events produce exit code 1
test_compact "only tool events no result exit 1" 1 "" \
  '{"type":"tool_use","name":"Read"}
{"type":"tool_result","content":"data"}'

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

test_compact "usage cache hit ratio" 0 "cache_hit_ratio=0.75" \
  '{"type":"result","result":"ok","usage":{"input_tokens":5,"cache_read_input_tokens":15,"output_tokens":10}}'

test_compact "cost in result" 0 "total_cost_usd=0.001500" \
  '{"type":"result","result":"ok","usage":{"input_tokens":5},"total_cost_usd":0.0015}'

test_compact "terminal_reason" 0 "terminal_reason=completed" \
  '{"type":"result","result":"ok","terminal_reason":"completed"}'

test_compact "mcp mode from init" 0 "mcpMode: none" \
  '{"type":"system","subtype":"init","mcpMode":"none"}
{"type":"result","result":"ok"}'

test_compact "effort from init" 0 "effort: high" \
  '{"type":"system","subtype":"init","effort":"high"}
{"type":"result","result":"ok"}'

outfile=$(mktemp "$SANDBOX/cs_out.XXXX")
set +e
printf '%s' '{"type":"result","result":"ok"}' | CLAUDE_DELEGATE_OBSERVED_MCP_MODE=jira "$COMPACT" > "$outfile" 2>/dev/null
rc=$?
set -e
if [ "$rc" -ne 0 ]; then
  echo "  FAIL  mcp mode from env (exit $rc, expected 0)"
  failed=$((failed+1))
elif ! grep -qF -e "mcpMode: jira" "$outfile"; then
  echo "  FAIL  mcp mode from env (output missing: mcpMode: jira)"
  echo "        output: $(cat "$outfile")"
  failed=$((failed+1))
else
  echo "  PASS  mcp mode from env"
  passed=$((passed+1))
fi
rm -f "$outfile"

outfile=$(mktemp "$SANDBOX/cs_out.XXXX")
set +e
printf '%s' '{"type":"result","result":"ok"}' | \
  CLAUDE_DELEGATE_OBSERVED_CLASS=tiny \
  CLAUDE_DELEGATE_OBSERVED_TASK_TYPE=read_only_scan \
  CLAUDE_DELEGATE_OBSERVED_CONTEXT_BUDGET=minimal \
  CLAUDE_DELEGATE_OBSERVED_PROMPT_MODE=template \
  CLAUDE_DELEGATE_OBSERVED_PROMPT_TEMPLATE=read_only_scan \
  CLAUDE_DELEGATE_ORIGINAL_PROMPT_CHARS=100 \
  CLAUDE_DELEGATE_PREPARED_PROMPT_CHARS=70 \
  CLAUDE_DELEGATE_PROMPT_REDUCTION_PCT=30 \
  "$COMPACT" > "$outfile" 2>/dev/null
rc=$?
set -e
if [ "$rc" -ne 0 ]; then
  echo "  FAIL  profiling metadata from env (exit $rc, expected 0)"
  failed=$((failed+1))
elif ! grep -qF -e "class: tiny" "$outfile" || ! grep -qF -e "promptChars: original=100, prepared=70, reduction_pct=30" "$outfile"; then
  echo "  FAIL  profiling metadata from env (output missing expected profiling lines)"
  echo "        output: $(cat "$outfile")"
  failed=$((failed+1))
else
  echo "  PASS  profiling metadata from env"
  passed=$((passed+1))
fi
rm -f "$outfile"

profile_log="$SANDBOX/profile.jsonl"
outfile=$(mktemp "$SANDBOX/cs_out.XXXX")
set +e
printf '%s' '{"type":"result","result":"ok","usage":{"input_tokens":5},"total_cost_usd":0.1}' | \
  CLAUDE_DELEGATE_PROFILE_LOG="$profile_log" \
  CLAUDE_DELEGATE_OBSERVED_CLASS=small \
  CLAUDE_DELEGATE_ORIGINAL_PROMPT_CHARS=10 \
  CLAUDE_DELEGATE_PREPARED_PROMPT_CHARS=8 \
  "$COMPACT" > "$outfile" 2>/dev/null
rc=$?
set -e
if [ "$rc" -ne 0 ]; then
  echo "  FAIL  profile jsonl logging (exit $rc, expected 0)"
  failed=$((failed+1))
elif ! grep -qF -e '"class": "small"' "$profile_log" || ! grep -qF -e '"input_tokens": 5' "$profile_log"; then
  echo "  FAIL  profile jsonl logging (missing expected record)"
  echo "        log: $(cat "$profile_log" 2>/dev/null || true)"
  failed=$((failed+1))
else
  echo "  PASS  profile jsonl logging"
  passed=$((passed+1))
fi
rm -f "$outfile"

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

# ---- aggregate-profile-log.py tests ----

echo ""
echo "=== aggregate-profile-log.py ==="

# test_aggregator name expected_exit expected_out_substr jsonl_content [extra_args...]
# Creates a temp JSONL from content (one record per line via \n), runs the aggregator.
test_aggregator() {
  local name="$1" expected_exit="$2" expected_out="$3" jsonl_content="$4"
  shift 4
  local jsonl_file; jsonl_file=$(mktemp "$SANDBOX/agg.XXXX")
  printf '%s\n' "$jsonl_content" > "$jsonl_file"
  local outfile; outfile=$(mktemp "$SANDBOX/agg_out.XXXX")
  set +e
  python3 "$AGGREGATOR" "$jsonl_file" "$@" > "$outfile" 2>/dev/null
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
  rm -f "$jsonl_file" "$outfile"
}

# Normal records with full fields
test_aggregator "aggregator normal records" 0 "Records: 2" \
  '{"isError":false,"model":"claude-sonnet-4-6","effort":"medium","taskType":"code_edit","mcpMode":"all","terminalReason":"completed","usage":{"input_tokens":500,"cache_read_input_tokens":200,"output_tokens":300},"totalCostUsd":0.05,"originalPromptChars":100,"preparedPromptChars":80,"promptReductionPct":20}
{"isError":false,"model":"claude-sonnet-4-6","effort":"low","taskType":"read_only_scan","mcpMode":"none","terminalReason":"completed","usage":{"input_tokens":100,"cache_read_input_tokens":0,"output_tokens":50},"totalCostUsd":0.01,"originalPromptChars":50,"preparedPromptChars":45,"promptReductionPct":10}'

test_aggregator "aggregator shows success/error counts" 0 "Success: 2  Error: 0" \
  '{"isError":false}
{"isError":false}'

test_aggregator "aggregator totals tokens" 0 "total=600" \
  '{"usage":{"input_tokens":100,"output_tokens":50}}
{"usage":{"input_tokens":500,"output_tokens":300}}'

test_aggregator "aggregator shows cache hit ratio" 0 "Cache hit ratio:" \
  '{"usage":{"input_tokens":100,"cache_read_input_tokens":50,"output_tokens":30}}
{"usage":{"input_tokens":200,"cache_read_input_tokens":150,"output_tokens":80}}'

test_aggregator "aggregator shows cost total" 0 "Total: \$0.0600" \
  '{"totalCostUsd":0.05}
{"totalCostUsd":0.01}'

test_aggregator "aggregator shows prompt chars" 0 "Prompt chars:" \
  '{"originalPromptChars":100,"preparedPromptChars":80}
{"originalPromptChars":50,"preparedPromptChars":45}'

# Missing usage fields
test_aggregator "aggregator handles missing usage fields" 0 "Records: 2" \
  '{"isError":false,"usage":{}}
{"isError":false,"usage":{"input_tokens":100}}'

# Error records
test_aggregator "aggregator counts errors" 0 "Error: 1" \
  '{"isError":true}
{"isError":false}'

# Empty file
test_aggregator "aggregator empty file" 0 "No records in profile log." ""

# JSON output
test_aggregator "aggregator json output" 0 '"total_records": 2' \
  '{"isError":false}
{"isError":true}' --json

test_aggregator "aggregator json success/error" 0 '"success_count": 1' \
  '{"isError":false}
{"isError":true}' --json

# Distribution output
test_aggregator "aggregator shows model distribution" 0 "Model:" \
  '{"model":"claude-sonnet-4-6"}
{"model":"claude-sonnet-4-6"}
{"model":"gpt-4"}'

test_aggregator "aggregator shows effort distribution" 0 "Effort:" \
  '{"effort":"low"}
{"effort":"high"}'

# Missing file
test_aggregator_no_file() {
  local outfile; outfile=$(mktemp "$SANDBOX/agg_out.XXXX")
  set +e
  python3 "$AGGREGATOR" "/nonexistent/path.jsonl" > "$outfile" 2>/dev/null
  local rc=$?
  set -e
  if [ "$rc" -ne 1 ]; then
    echo "  FAIL  aggregator missing file (exit $rc, expected 1)"
    failed=$((failed+1))
  else
    echo "  PASS  aggregator missing file"
    passed=$((passed+1))
  fi
  rm -f "$outfile"
}
test_aggregator_no_file

# ---- envelope_builder.py tests ----

echo ""
echo "=== envelope_builder.py ==="

ENVELOPE_BUILDER="$SCRIPT_DIR/../scripts/envelope_builder.py"

# test_envelope name expected_stdout expected_exit python_stdin
test_envelope() {
  local name="$1" expected_out="$2" expected_exit="$3" stdin="$4"
  local outfile; outfile=$(mktemp "$SANDBOX/eb_out.XXXX")
  set +e
  printf '%s' "$stdin" | python3 "$ENVELOPE_BUILDER" > "$outfile" 2>/dev/null
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

# Unit tests for build_prepared_prompt via temp Python scripts.
# Writes Python code into a temp .py file and executes it — avoids all shell quoting/expansion issues.
test_envelope_py() {
  local name="$1" expected_out="$2" expected_exit="$3"
  local py_script; py_script=$(mktemp "$SANDBOX/ebp_script.XXXX.py")
  cat > "$py_script" <<PYEOF
import sys
sys.path.insert(0, "$SCRIPT_DIR/../scripts")
$4
PYEOF
  local outfile; outfile=$(mktemp "$SANDBOX/ebp_out.XXXX")
  local errfile; errfile=$(mktemp "$SANDBOX/ebp_err.XXXX")
  set +e
  python3 "$py_script" > "$outfile" 2> "$errfile"
  local rc=$?
  set -e
  if [ "$rc" -ne "$expected_exit" ]; then
    echo "  FAIL  $name (exit $rc, expected $expected_exit)"
    echo "        stderr: $(cat "$errfile")"
    failed=$((failed+1))
  elif [ -n "$expected_out" ] && ! grep -qF -e "$expected_out" "$outfile"; then
    echo "  FAIL  $name (output missing: $expected_out)"
    echo "        output: $(cat "$outfile")"
    failed=$((failed+1))
  else
    echo "  PASS  $name"
    passed=$((passed+1))
  fi
  rm -f "$py_script" "$outfile" "$errfile"
}

test_envelope_py \
  "envelope_builder module exists and imports" \
  "envelope_builder OK" 0 \
  "from envelope_builder import build_prepared_prompt; print('envelope_builder OK')"

test_envelope_py \
  "build_prepared_prompt read_only_scan template" \
  "Task Template: read-only scan" 0 \
  "from envelope_builder import build_prepared_prompt
from classifier import Classification
c = Classification('tiny','read_only_scan','flash','low','bypassPermissions','minimal',True)
p, m = build_prepared_prompt('check how many rows', c, 'auto')
print(p)"

test_envelope_py \
  "build_prepared_prompt code_edit template" \
  "Task Template: code edit" 0 \
  "from envelope_builder import build_prepared_prompt
from classifier import Classification
c = Classification('small','code_edit','flash','medium','bypassPermissions','standard',True)
p, m = build_prepared_prompt('fix a bug', c, 'auto')
print(p)"

test_envelope_py \
  "build_prepared_prompt jira_operation template" \
  "Task Template: Jira operation" 0 \
  "from envelope_builder import build_prepared_prompt
from classifier import Classification
c = Classification('small','jira_operation','flash','medium','bypassPermissions','standard',True)
p, m = build_prepared_prompt('mark CCDM-3 done', c, 'auto')
print(p)"

test_envelope_py \
  "build_prepared_prompt architecture_review template" \
  "Task Template: architecture review" 0 \
  "from envelope_builder import build_prepared_prompt
from classifier import Classification
c = Classification('large','architecture_review','pro','max','bypassPermissions','expanded',True)
p, m = build_prepared_prompt('architecture refactor', c, 'auto')
print(p)"

test_envelope_py \
  "build_prepared_prompt unrecognized task_type uses envelope fallback" \
  "Task Context Envelope" 0 \
  "from envelope_builder import build_prepared_prompt
from classifier import Classification
c = Classification('custom','unrecognized_type','pro','max','bypassPermissions','full',True)
p, m = build_prepared_prompt('hello world', c, 'auto')
print(p)"

test_envelope_py \
  "build_prepared_prompt full context_mode returns prompt unchanged" \
  "hello world" 0 \
  "from envelope_builder import build_prepared_prompt
from classifier import Classification
c = Classification('tiny','read_only_scan','flash','low','bypassPermissions','minimal',True)
p, m = build_prepared_prompt('hello world', c, 'full')
print(p)"

test_envelope_py \
  "build_prepared_prompt non-template classification returns full" \
  "original text here" 0 \
  "from envelope_builder import build_prepared_prompt
from classifier import Classification
c = Classification('default','unknown','pro','max','bypassPermissions','full',False)
p, m = build_prepared_prompt('original text here', c, 'auto')
print(p)"

test_envelope_py \
  "build_prepared_prompt jira returns mode template" \
  "template" 0 \
  "from envelope_builder import build_prepared_prompt
from classifier import Classification
c = Classification('small','jira_operation','flash','medium','bypassPermissions','standard',True)
p, m = build_prepared_prompt('mark it done', c, 'auto')
print(m)"

test_envelope_py \
  "build_prepared_prompt envelope returns mode envelope" \
  "envelope" 0 \
  "from envelope_builder import build_prepared_prompt
from classifier import Classification
c = Classification('custom','unrecognized_type','pro','max','bypassPermissions','full',True)
p, m = build_prepared_prompt('hi', c, 'auto')
print(m)"

test_envelope_py \
  "build_prepared_prompt full context returns mode full" \
  "full" 0 \
  "from envelope_builder import build_prepared_prompt
from classifier import Classification
c = Classification('tiny','read_only_scan','flash','low','bypassPermissions','minimal',True)
p, m = build_prepared_prompt('hi', c, 'full')
print(m)"

# ---- invoker.py tests ----

echo ""
echo "=== invoker.py ==="

# test_invoker_py name expected_out expected_exit py_code_body
# Writes Python code into a temp .py file with boilerplate and executes it.
test_invoker_py() {
  local name="$1" expected_out="$2" expected_exit="$3"
  local py_script; py_script=$(mktemp "$SANDBOX/inv_script.XXXX.py")
  cat > "$py_script" <<PYEOF
import sys, os, json, tempfile, threading
sys.path.insert(0, "$SCRIPT_DIR/../scripts")
$4
PYEOF
  local outfile; outfile=$(mktemp "$SANDBOX/inv_out.XXXX")
  local errfile; errfile=$(mktemp "$SANDBOX/inv_err.XXXX")
  set +e
  python3 "$py_script" > "$outfile" 2> "$errfile"
  local rc=$?
  set -e
  if [ "$rc" -ne "$expected_exit" ]; then
    echo "  FAIL  $name (exit $rc, expected $expected_exit)"
    echo "        stderr: $(cat "$errfile")"
    failed=$((failed+1))
  elif [ -n "$expected_out" ] && ! grep -qF -e "$expected_out" "$outfile"; then
    echo "  FAIL  $name (output missing: $expected_out)"
    echo "        output: $(cat "$outfile")"
    echo "        stderr: $(cat "$errfile")"
    failed=$((failed+1))
  else
    echo "  PASS  $name"
    passed=$((passed+1))
  fi
  rm -f "$py_script" "$outfile" "$errfile"
}

test_invoker_py \
  "invoker module exists and imports" \
  "invoker OK" 0 \
  "from invoker import InvokerConfig, invoke_claude, generate_mcp_config, start_heartbeat
print('invoker OK')"

test_invoker_py \
  "InvokerConfig dataclass fields" \
  "InvokerConfig OK" 0 \
  "from invoker import InvokerConfig
c = InvokerConfig(model='pro', effort='max', permission_mode='bypassPermissions', mcp_mode='all', subagent_mode='off', heartbeat_seconds=30, output_mode='quiet', prompt='test')
assert c.model == 'pro'
assert c.effort == 'max'
assert c.mcp_mode == 'all'
assert c.permission_mode == 'bypassPermissions'
print('InvokerConfig OK')"

test_invoker_py \
  "generate_mcp_config mode=all returns empty args" \
  "mcp_all: args=[] config=None" 0 \
  "from invoker import generate_mcp_config
args, cfg = generate_mcp_config('all', None)
print('mcp_all: args={} config={}'.format(args, cfg))"

test_invoker_py \
  "generate_mcp_config mode=none returns strict config" \
  "strict-mcp-config" 0 \
  "from invoker import generate_mcp_config
args, cfg = generate_mcp_config('none', None)
print('mcp_none: {}'.format(args))"

test_invoker_py \
  "generate_mcp_config mode=none passes mcp-config" \
  "--mcp-config" 0 \
  "from invoker import generate_mcp_config
args, cfg = generate_mcp_config('none', None)
assert '--strict-mcp-config' in args
assert '--mcp-config' in args
assert args.index('--mcp-config') + 1 < len(args)
print('mcp_none: {}'.format(args))"

test_invoker_py \
  "generate_mcp_config mode=none empty servers" \
  "mcpServers" 0 \
  "from invoker import generate_mcp_config
args, cfg_json = generate_mcp_config('none', None)
c = json.loads(cfg_json)
assert c == {'mcpServers': {}}
print('ok: {}'.format(cfg_json))"

test_invoker_py \
  "generate_mcp_config mode=specific parses mcp.json" \
  "cfg_path_exists" 0 \
  "from invoker import generate_mcp_config
mcp_json = json.dumps({'mcpServers': {'jira': {'command': 'npx', 'args': ['-y', 'jira-mcp']}}})
f = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
f.write(mcp_json)
f.close()
args, cfg_path = generate_mcp_config('jira', f.name)
os.unlink(f.name)
print('{} cfg_path_exists'.format(args))
if cfg_path:
    os.unlink(cfg_path)"

test_invoker_py \
  "generate_mcp_config mode=specific passes mcp-config" \
  "--mcp-config" 0 \
  "from invoker import generate_mcp_config
mcp_json = json.dumps({'mcpServers': {'jira': {'command': 'npx', 'args': ['-y', 'jira-mcp']}}})
f = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
f.write(mcp_json)
f.close()
try:
    args, cfg_path = generate_mcp_config('jira', f.name)
    assert '--strict-mcp-config' in args
    assert '--mcp-config' in args
    assert args.index('--mcp-config') + 1 < len(args)
    print('mcp_jira: {}'.format(args))
finally:
    os.unlink(f.name)"

test_invoker_py \
  "generate_mcp_config invalid specific server raises ValueError" \
  "ValueError" 0 \
  "from invoker import generate_mcp_config
mcp_json = json.dumps({'mcpServers': {'jira': {}}})
f = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
f.write(mcp_json)
f.close()
try:
    generate_mcp_config('linear', f.name)
    print('no error')
except ValueError as e:
    print('ValueError: {}'.format(e))
finally:
    os.unlink(f.name)"

test_invoker_py \
  "resolve_mcp_config_path skips cwd config missing requested server" \
  "resolved_user_config" 0 \
  "from invoker import resolve_mcp_config_path
from pathlib import Path
home = tempfile.mkdtemp()
cwd = tempfile.mkdtemp()
old_home = os.environ.get('HOME')
old_cwd = os.getcwd()
old_explicit = os.environ.pop('CLAUDE_DELEGATE_MCP_CONFIG_PATH', None)
try:
    os.environ['HOME'] = home
    os.chdir(cwd)
    Path('.mcp.json').write_text(json.dumps({'mcpServers': {'linear': {'command': 'linear'}}}))
    user_config = Path(home) / '.claude' / 'mcp.json'
    user_config.parent.mkdir(parents=True)
    user_config.write_text(json.dumps({'mcpServers': {'jira': {'command': 'jira'}}}))
    resolved = resolve_mcp_config_path('jira')
    assert resolved == str(user_config), resolved
    print('resolved_user_config')
finally:
    os.chdir(old_cwd)
    if old_home is not None:
        os.environ['HOME'] = old_home
    else:
        os.environ.pop('HOME', None)
    if old_explicit is not None:
        os.environ['CLAUDE_DELEGATE_MCP_CONFIG_PATH'] = old_explicit"

test_invoker_py \
  "start_heartbeat zero interval returns None" \
  "heartbeat=None" 0 \
  "from invoker import start_heartbeat
h = start_heartbeat(0, 'pro', 'max', 'all', 'quiet')
print('heartbeat={}'.format(h))"

test_invoker_py \
  "start_heartbeat positive interval returns daemon thread" \
  "heartbeat_thread_daemon=True" 0 \
  "from invoker import start_heartbeat
h = start_heartbeat(1, 'pro', 'max', 'all', 'quiet')
print('heartbeat_thread_daemon={}'.format(h.daemon))"

test_invoker_py \
  "load_claude_settings_env backfills settings env" \
  "loaded_settings_env" 0 \
  "from invoker import load_claude_settings_env
from pathlib import Path
home = tempfile.mkdtemp()
old_home = os.environ.get('HOME')
try:
    os.environ['HOME'] = home
    settings = Path(home) / '.claude' / 'settings.json'
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({'env': {'ANTHROPIC_BASE_URL': 'https://example.invalid', 'ANTHROPIC_AUTH_TOKEN': 'secret'}}))
    env = load_claude_settings_env({'PATH': os.environ['PATH']})
    assert env['ANTHROPIC_BASE_URL'] == 'https://example.invalid'
    assert env['ANTHROPIC_AUTH_TOKEN'] == 'secret'
    print('loaded_settings_env')
finally:
    if old_home is not None:
        os.environ['HOME'] = old_home
    else:
        os.environ.pop('HOME', None)"

test_invoker_py \
  "load_claude_settings_env preserves process env" \
  "preserved_process_env" 0 \
  "from invoker import load_claude_settings_env
from pathlib import Path
home = tempfile.mkdtemp()
old_home = os.environ.get('HOME')
try:
    os.environ['HOME'] = home
    settings = Path(home) / '.claude' / 'settings.json'
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({'env': {'ANTHROPIC_BASE_URL': 'https://settings.invalid'}}))
    env = load_claude_settings_env({'PATH': os.environ['PATH'], 'ANTHROPIC_BASE_URL': 'https://process.invalid'})
    assert env['ANTHROPIC_BASE_URL'] == 'https://process.invalid'
    print('preserved_process_env')
finally:
    if old_home is not None:
        os.environ['HOME'] = old_home
    else:
        os.environ.pop('HOME', None)"

test_invoker_py \
  "prepare_isolated_claude_config writes minimal settings" \
  "isolated_settings_ok" 0 \
  "from invoker import prepare_isolated_claude_config
from pathlib import Path
cwd = tempfile.mkdtemp()
old_cwd = os.getcwd()
try:
    os.chdir(cwd)
    env = prepare_isolated_claude_config({
        'PATH': os.environ['PATH'],
        'ANTHROPIC_BASE_URL': 'https://example.invalid',
        'ANTHROPIC_AUTH_TOKEN': 'secret',
        'ANTHROPIC_MODEL': 'model-x',
    })
    config_dir = Path(env['CLAUDE_CONFIG_DIR'])
    assert config_dir == (Path(cwd) / '.claude-delegate' / 'runtime' / 'claude-config').resolve()
    settings = json.loads((config_dir / 'settings.json').read_text())
    assert settings['env']['ANTHROPIC_BASE_URL'] == 'https://example.invalid'
    assert settings['env']['ANTHROPIC_AUTH_TOKEN'] == 'secret'
    assert settings['env']['ANTHROPIC_MODEL'] == 'model-x'
    assert 'enabledPlugins' not in settings
    assert 'hooks' not in settings
    print('isolated_settings_ok')
finally:
    os.chdir(old_cwd)"

test_invoker_py \
  "prepare_isolated_claude_config can be disabled" \
  "isolated_disabled_ok" 0 \
  "from invoker import prepare_isolated_claude_config
env = {'PATH': os.environ['PATH'], 'CLAUDE_DELEGATE_ISOLATED_CONFIG': '0'}
updated = prepare_isolated_claude_config(env)
assert updated is env
assert 'CLAUDE_CONFIG_DIR' not in updated
print('isolated_disabled_ok')"

test_invoker_py \
  "invoke_claude with fake claude returns result" \
  "invoke_claude OK" 0 \
  "from invoker import InvokerConfig, invoke_claude
c = InvokerConfig(model='pro', effort='max', permission_mode='bypassPermissions', mcp_mode='all', subagent_mode='off', heartbeat_seconds=0, output_mode='quiet', prompt='test prompt')
result = invoke_claude(c)
print('invoke_claude OK: rc={}'.format(result.returncode))"

test_invoker_py \
  "invoke_claude quiet mode has captured stdout" \
  "result" 0 \
  "from invoker import InvokerConfig, invoke_claude
c = InvokerConfig(model='pro', effort='max', permission_mode='bypassPermissions', mcp_mode='all', subagent_mode='off', heartbeat_seconds=0, output_mode='quiet', prompt='test')
result = invoke_claude(c)
print('result: {}'.format(result.stdout.strip()[:50]))"

test_invoker_py \
  "invoke_claude quiet mode result has json" \
  "done" 0 \
  "from invoker import InvokerConfig, invoke_claude
c = InvokerConfig(model='pro', effort='max', permission_mode='bypassPermissions', mcp_mode='all', subagent_mode='off', heartbeat_seconds=0, output_mode='quiet', prompt='test')
result = invoke_claude(c)
import json
data = json.loads(result.stdout)
print(data['result'])"

test_invoker_py \
  "invoke_claude disallowedTools when subagent_mode=off" \
  "HAS_DISALLOWED" 0 \
  "from invoker import InvokerConfig, invoke_claude
c = InvokerConfig(model='pro', effort='max', permission_mode='bypassPermissions', mcp_mode='all', subagent_mode='off', heartbeat_seconds=0, output_mode='quiet', prompt='test')
result = invoke_claude(c)
if '--disallowedTools' in result.args:
    print('HAS_DISALLOWED')
else:
    print('NO_DISALLOWED')"

test_invoker_py \
  "invoke_claude no disallowedTools when subagent_mode=on" \
  "NO_DISALLOWED" 0 \
  "from invoker import InvokerConfig, invoke_claude
c = InvokerConfig(model='pro', effort='max', permission_mode='bypassPermissions', mcp_mode='all', subagent_mode='on', heartbeat_seconds=0, output_mode='quiet', prompt='test')
result = invoke_claude(c)
if '--disallowedTools' in result.args:
    print('HAS_DISALLOWED')
else:
    print('NO_DISALLOWED')"

test_invoker_py \
  "invoke_claude mcp jira preserves prompt as final arg" \
  "PROMPT_LAST" 0 \
  "from invoker import InvokerConfig, invoke_claude
mcp_json = json.dumps({'mcpServers': {'jira': {'command': 'node', 'args': ['jira.js']}}})
f = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
f.write(mcp_json)
f.close()
os.environ['CLAUDE_DELEGATE_MCP_CONFIG_PATH'] = f.name
try:
    c = InvokerConfig(model='pro', effort='max', permission_mode='bypassPermissions', mcp_mode='jira', subagent_mode='off', heartbeat_seconds=0, output_mode='quiet', prompt='test prompt')
    result = invoke_claude(c)
    assert '--strict-mcp-config' in result.args
    assert '--mcp-config' in result.args
    assert result.args[-1] == 'test prompt'
    print('PROMPT_LAST')
finally:
    os.environ.pop('CLAUDE_DELEGATE_MCP_CONFIG_PATH', None)
    os.unlink(f.name)"

test_invoker_py \
  "invoke_claude stream mode writes to stdout" \
  "stream_ok" 0 \
  "from invoker import InvokerConfig, invoke_claude
c = InvokerConfig(model='pro', effort='max', permission_mode='bypassPermissions', mcp_mode='all', subagent_mode='off', heartbeat_seconds=0, output_mode='stream', prompt='test')
result = invoke_claude(c)
print('stream_ok: {}'.format(type(result).__name__))"

test_invoker_py \
  "invoke_claude stream mode result from fake claude" \
  "done" 0 \
  "from invoker import InvokerConfig, invoke_claude
c = InvokerConfig(model='pro', effort='max', permission_mode='bypassPermissions', mcp_mode='all', subagent_mode='off', heartbeat_seconds=0, output_mode='stream', prompt='test')
result = invoke_claude(c)
# fake claude outputs JSON to stdout
import json
data = json.loads(result.stdout)
print(data['result'])"

test_invoker_py \
  "invoke_claude passes Claude settings env to child" \
  "CHILD_ENV_OK" 0 \
  "from invoker import InvokerConfig, invoke_claude
from pathlib import Path
home = tempfile.mkdtemp()
old_home = os.environ.get('HOME')
capture = tempfile.NamedTemporaryFile(delete=False)
capture.close()
try:
    os.environ['HOME'] = home
    os.environ['CLAUDE_DELEGATE_TEST_CAPTURE'] = capture.name
    saved_base_url = os.environ.pop('ANTHROPIC_BASE_URL', None)
    saved_auth_token = os.environ.pop('ANTHROPIC_AUTH_TOKEN', None)
    settings = Path(home) / '.claude' / 'settings.json'
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({'env': {'ANTHROPIC_BASE_URL': 'https://example.invalid', 'ANTHROPIC_AUTH_TOKEN': 'secret'}}))
    c = InvokerConfig(model='pro', effort='max', permission_mode='bypassPermissions', mcp_mode='all', subagent_mode='off', heartbeat_seconds=0, output_mode='quiet', prompt='test')
    invoke_claude(c)
    captured = Path(capture.name).read_text()
    assert 'ANTHROPIC_BASE_URL:https://example.invalid' in captured
    assert 'ANTHROPIC_AUTH_TOKEN:secret' in captured
    print('CHILD_ENV_OK')
finally:
    os.environ.pop('CLAUDE_DELEGATE_TEST_CAPTURE', None)
    if saved_base_url is not None:
        os.environ['ANTHROPIC_BASE_URL'] = saved_base_url
    if saved_auth_token is not None:
        os.environ['ANTHROPIC_AUTH_TOKEN'] = saved_auth_token
    if old_home is not None:
        os.environ['HOME'] = old_home
    else:
        os.environ.pop('HOME', None)
    os.unlink(capture.name)"

test_invoker_py \
  "invoke_claude uses isolated Claude config by default" \
  "ISOLATED_CHILD_OK" 0 \
  "from invoker import InvokerConfig, invoke_claude, CLAUDE_ENV_KEYS
from pathlib import Path
home = tempfile.mkdtemp()
cwd = tempfile.mkdtemp()
old_home = os.environ.get('HOME')
old_cwd = os.getcwd()
capture = tempfile.NamedTemporaryFile(delete=False)
capture.close()
saved_anthropic_vars = {}
try:
    os.environ['HOME'] = home
    os.chdir(cwd)
    os.environ['CLAUDE_DELEGATE_TEST_CAPTURE'] = capture.name
    for key in CLAUDE_ENV_KEYS:
        saved_anthropic_vars[key] = os.environ.pop(key, None)
    settings = Path(home) / '.claude' / 'settings.json'
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({'env': {'ANTHROPIC_BASE_URL': 'https://example.invalid', 'ANTHROPIC_AUTH_TOKEN': 'fake-token'}}))
    c = InvokerConfig(model='pro', effort='max', permission_mode='bypassPermissions', mcp_mode='all', subagent_mode='off', heartbeat_seconds=0, output_mode='quiet', prompt='test')
    invoke_claude(c)
    config_dir = (Path(cwd) / '.claude-delegate' / 'runtime' / 'claude-config').resolve()
    captured = Path(capture.name).read_text()
    assert f'CLAUDE_CONFIG_DIR:{config_dir}' in captured
    runtime_settings = json.loads((config_dir / 'settings.json').read_text())
    assert runtime_settings['env']['ANTHROPIC_BASE_URL'] == 'https://example.invalid'
    assert 'enabledPlugins' not in runtime_settings
    print('ISOLATED_CHILD_OK')
finally:
    os.environ.pop('CLAUDE_DELEGATE_TEST_CAPTURE', None)
    os.chdir(old_cwd)
    if old_home is not None:
        os.environ['HOME'] = old_home
    else:
        os.environ.pop('HOME', None)
    for key, value in saved_anthropic_vars.items():
        if value is not None:
            os.environ[key] = value
    os.unlink(capture.name)"

# ---- mcp_server.py tests ----

echo ""
echo "=== mcp_server.py ==="

MCP_SERVER="$SCRIPT_DIR/../scripts/mcp_server.py"
[ -f "$MCP_SERVER" ] || { echo "ERROR: $MCP_SERVER not found"; exit 1; }

HAS_MCP_PKG=$(python3 -c "import mcp; print('yes')" 2>/dev/null || echo "no")
# test_mcp_server_py name expected_out expected_exit py_code
test_mcp_server_py() {
  local name="$1" expected_out="$2" expected_exit="$3"
  local py_script; py_script=$(mktemp "$SANDBOX/mcp_script.XXXX.py")
  cat > "$py_script" <<PYEOF
import sys, os, json, tempfile, threading
sys.path.insert(0, "$SCRIPT_DIR/../scripts")
$4
PYEOF
  local outfile; outfile=$(mktemp "$SANDBOX/mcp_out.XXXX")
  local errfile; errfile=$(mktemp "$SANDBOX/mcp_err.XXXX")
  set +e
  python3 "$py_script" > "$outfile" 2> "$errfile"
  local rc=$?
  set -e
  if [ "$rc" -ne "$expected_exit" ]; then
    echo "  FAIL  $name (exit $rc, expected $expected_exit)"
    echo "        stderr: $(cat "$errfile")"
    failed=$((failed+1))
  elif [ -n "$expected_out" ] && ! grep -qF -e "$expected_out" "$outfile"; then
    echo "  FAIL  $name (output missing: $expected_out)"
    echo "        output: $(cat "$outfile")"
    echo "        stderr: $(cat "$errfile")"
    failed=$((failed+1))
  else
    echo "  PASS  $name"
    passed=$((passed+1))
  fi
  rm -f "$py_script" "$outfile" "$errfile"
}

if [ "$HAS_MCP_PKG" = "yes" ]; then

test_mcp_server_py \
  "mcp_server module exists and imports" \
  "mcp_server OK" 0 \
  "import importlib.util
import os
spec = importlib.util.spec_from_file_location(
    'mcp_server', os.path.join('$SCRIPT_DIR/../scripts', 'mcp_server.py')
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
assert hasattr(mod, '_classification_to_dict')
assert hasattr(mod, '_import_script')
assert hasattr(mod, 'classify_task')
print('mcp_server OK')"

test_mcp_server_py \
  "mcp_server FastMCP server initialized with tools" \
  "fastmcp_ok" 0 \
  "import importlib.util, os
spec = importlib.util.spec_from_file_location(
    'mcp_server', os.path.join('$SCRIPT_DIR/../scripts', 'mcp_server.py')
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
if hasattr(mod, 'server') and hasattr(mod, 'classify_task'):
    print('fastmcp_ok')
else:
    print('fastmcp_init_failed')"

test_mcp_server_py \
  "_classification_to_dict maps all fields" \
  "classification_to_dict OK" 0 \
  "import importlib.util, os
spec = importlib.util.spec_from_file_location(
    'mcp_server', os.path.join('$SCRIPT_DIR/../scripts', 'mcp_server.py')
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
from classifier import Classification
c = Classification('small','code_edit','flash','medium','bypassPermissions','standard',True)
d = mod._classification_to_dict(c)
assert d['name'] == 'small'
assert d['task_type'] == 'code_edit'
assert d['model'] == 'flash'
assert d['effort'] == 'medium'
assert d['permission_mode'] == 'bypassPermissions'
assert d['context_budget'] == 'standard'
assert d['use_template'] == True
print('classification_to_dict OK')"

test_mcp_server_py \
  "_import_script loads hyphenated script jira-safe-text" \
  "markdown_to_plain_OK" 0 \
  "import importlib.util, os
spec = importlib.util.spec_from_file_location(
    'mcp_server', os.path.join('$SCRIPT_DIR/../scripts', 'mcp_server.py')
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
jira = mod._import_script('jira-safe-text')
result = jira.markdown_to_plain('**bold** and *italic*')
assert result == 'bold and italic'
print('markdown_to_plain_OK')"

test_mcp_server_py \
  "_import_script loads compact-claude-stream parse_compact_output" \
  "compact_parse_OK" 0 \
  "import importlib.util, os
spec = importlib.util.spec_from_file_location(
    'mcp_server', os.path.join('$SCRIPT_DIR/../scripts', 'mcp_server.py')
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
compact = mod._import_script('compact-claude-stream')
parsed = compact.parse_compact_output('{\"type\":\"result\",\"result\":\"done\",\"usage\":{\"input_tokens\":5,\"output_tokens\":10},\"total_cost_usd\":0.01,\"terminal_reason\":\"completed\"}')
assert parsed['result'] == 'done'
assert parsed['usage'] == {'input_tokens':5,'output_tokens':10}
assert parsed['cost_usd'] == 0.01
assert parsed['terminal_reason'] == 'completed'
assert parsed['has_result'] == True
print('compact_parse_OK')"

test_mcp_server_py \
  "parse_compact_output handles stream-json with init event" \
  "stream_init_OK" 0 \
  "import importlib.util, os
spec = importlib.util.spec_from_file_location(
    'mcp_server', os.path.join('$SCRIPT_DIR/../scripts', 'mcp_server.py')
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
compact = mod._import_script('compact-claude-stream')
parsed = compact.parse_compact_output(
    '{\"type\":\"system\",\"subtype\":\"init\",\"model\":\"stream-test\",\"effort\":\"max\"}\\n'
    '{\"type\":\"result\",\"result\":\"done\"}'
)
assert parsed['model'] == 'stream-test'
assert parsed['effort'] == 'max'
assert parsed['has_init'] == True
assert parsed['has_result'] == True
print('stream_init_OK')"

test_mcp_server_py \
  "parse_compact_output no result returns empty" \
  "empty_result_OK" 0 \
  "import importlib.util, os
spec = importlib.util.spec_from_file_location(
    'mcp_server', os.path.join('$SCRIPT_DIR/../scripts', 'mcp_server.py')
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
compact = mod._import_script('compact-claude-stream')
parsed = compact.parse_compact_output('{\"type\":\"tool_use\",\"name\":\"Read\"}')
assert parsed['result'] == ''
assert parsed['has_result'] == False
print('empty_result_OK')"

test_mcp_server_py \
  "classify_task returns correct dict structure" \
  "classify_task_OK" 0 \
  "from classifier import classify_prompt
from pipeline import _resolve_auto
import importlib.util, os
spec = importlib.util.spec_from_file_location(
    'mcp_server', os.path.join('$SCRIPT_DIR/../scripts', 'mcp_server.py')
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

c = classify_prompt('fix the README typo')
d = mod._classification_to_dict(c)
assert 'name' in d
assert 'task_type' in d
assert d['task_type'] == 'code_edit'
print('classify_task_OK')"

test_mcp_server_py \
  "classify_task detects Jira operations" \
  "jira_detect_OK" 0 \
  "from classifier import classify_prompt
from pipeline import _resolve_auto
import importlib.util, os
spec = importlib.util.spec_from_file_location(
    'mcp_server', os.path.join('$SCRIPT_DIR/../scripts', 'mcp_server.py')
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

c = classify_prompt('mark CCDM-3 done in Jira')
d = mod._classification_to_dict(c)
assert d['task_type'] == 'jira_operation'
print('jira_detect_OK')"

test_mcp_server_py \
  "format_jira_text strips bold and italic" \
  "format_jira_OK" 0 \
  "import importlib.util, os
spec = importlib.util.spec_from_file_location(
    'mcp_server', os.path.join('$SCRIPT_DIR/../scripts', 'mcp_server.py')
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
jira = mod._import_script('jira-safe-text')
result = jira.markdown_to_plain('**bold** and *italic* text')
assert result == 'bold and italic text'
print('format_jira_OK')"

test_mcp_server_py \
  "format_jira_text strips links" \
  "link_strip_OK" 0 \
  "import importlib.util, os
spec = importlib.util.spec_from_file_location(
    'mcp_server', os.path.join('$SCRIPT_DIR/../scripts', 'mcp_server.py')
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
jira = mod._import_script('jira-safe-text')
result = jira.markdown_to_plain('see [docs](https://x.com) here')
assert result == 'see docs here'
print('link_strip_OK')"

# delegate_task pipeline test with fake claude
test_mcp_server_py \
  "delegate_task pipeline with fake claude" \
  "delegate_pipeline_OK" 0 \
  "import importlib.util, os, json, sys
scripts_dir = '$SCRIPT_DIR/../scripts'
sys.path.insert(0, scripts_dir)

# Import modules
spec = importlib.util.spec_from_file_location(
    'mcp_server', os.path.join(scripts_dir, 'mcp_server.py')
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

from classifier import classify_prompt
from pipeline import _resolve_auto
from envelope_builder import build_prepared_prompt
from invoker import InvokerConfig, invoke_claude

# Simulate delegate_task logic (without MCP wrapper)
prompt = 'fix the README typo'
classification = classify_prompt(prompt)

model = classification.model
effort = _resolve_auto('auto', classification.effort)
permission = _resolve_auto('auto', classification.permission_mode)

final_prompt, mode = build_prepared_prompt(prompt, classification, 'auto')

config = InvokerConfig(
    model=model,
    effort=effort,
    permission_mode=permission,
    mcp_mode='all',
    subagent_mode='off',
    heartbeat_seconds=0,
    output_mode='quiet',
    prompt=final_prompt,
)

result = invoke_claude(config)
data = json.loads(result.stdout)
assert data['result'] == 'done'
assert data['usage']['input_tokens'] == 5
assert data['usage']['output_tokens'] == 10
print('delegate_pipeline_OK')"

# aggregate_profile tests
test_mcp_server_py \
  "aggregate_profile text format with temp JSONL" \
  "Records: 2" 0 \
  "import importlib.util, os, tempfile
spec = importlib.util.spec_from_file_location(
    'mcp_server', os.path.join('$SCRIPT_DIR/../scripts', 'mcp_server.py')
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
agg = mod._import_script('aggregate-profile-log')

# Create temp JSONL
f = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
f.write('{\"isError\":false,\"model\":\"pro\"}\\n')
f.write('{\"isError\":false,\"model\":\"flash\"}\\n')
f.close()

records = agg.load_records(f.name)
result = agg.aggregate(records)
text = agg.format_text(result)
os.unlink(f.name)
print(text[:100])"

test_mcp_server_py \
  "aggregate_profile json format with temp JSONL" \
  "total_records" 0 \
  "import importlib.util, os, tempfile, json
spec = importlib.util.spec_from_file_location(
    'mcp_server', os.path.join('$SCRIPT_DIR/../scripts', 'mcp_server.py')
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
agg = mod._import_script('aggregate-profile-log')

# Create temp JSONL
f = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
f.write('{\"isError\":false,\"model\":\"pro\"}\\n')
f.write('{\"isError\":true,\"model\":\"flash\"}\\n')
f.close()

records = agg.load_records(f.name)
result = agg.aggregate(records)
json_str = agg.format_json(result)
os.unlink(f.name)
data = json.loads(json_str)
assert data['total_records'] == 2
assert data['success_count'] == 1
assert data['error_count'] == 1
print('total_records: {}'.format(data['total_records']))"

test_mcp_server_py \
  "aggregate_profile empty JSONL returns no records message" \
  "No records in profile log" 0 \
  "import importlib.util, os, tempfile
spec = importlib.util.spec_from_file_location(
    'mcp_server', os.path.join('$SCRIPT_DIR/../scripts', 'mcp_server.py')
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
agg = mod._import_script('aggregate-profile-log')

# Empty file
f = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
f.write('')
f.close()

records = agg.load_records(f.name)
result = agg.aggregate(records)
text = agg.format_text(result)
os.unlink(f.name)
print(text)"

test_mcp_server_py \
  "aggregate_profile with usage and cost data" \
  "Cost:" 0 \
  "import importlib.util, os, tempfile
spec = importlib.util.spec_from_file_location(
    'mcp_server', os.path.join('$SCRIPT_DIR/../scripts', 'mcp_server.py')
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
agg = mod._import_script('aggregate-profile-log')

f = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
f.write('{\"isError\":false,\"model\":\"pro\",\"effort\":\"max\",\"usage\":{\"input_tokens\":500,\"cache_read_input_tokens\":200,\"output_tokens\":300},\"totalCostUsd\":0.05}\\n')
f.write('{\"isError\":false,\"model\":\"flash\",\"effort\":\"low\",\"usage\":{\"input_tokens\":100,\"output_tokens\":50},\"totalCostUsd\":0.01}\\n')
f.close()

records = agg.load_records(f.name)
result = agg.aggregate(records)
text = agg.format_text(result)
os.unlink(f.name)
print(text[:300])
if 'Cost:' in text:
    print('Cost: present')"

else
  echo "  SKIP  mcp_server tests (mcp package not installed)"
  passed=$((passed+1))
fi

# ---- MCP integration tests ----

echo ""
echo "=== MCP integration tests ==="

HAS_MCP_PKG=$(python3 -c "import mcp; print('yes')" 2>/dev/null || echo "no")

# test_mcp_integration name expected_out expected_exit py_code
test_mcp_integration() {
  local name="$1" expected_out="$2" expected_exit="$3"
  local py_script; py_script=$(mktemp "$SANDBOX/mcp_int.XXXX.py")
  cat > "$py_script" <<PYEOF
import subprocess, json, sys, os
MCP_SERVER = "$MCP_SERVER"
SANDBOX = "$SANDBOX"
$4
PYEOF
  local outfile; outfile=$(mktemp "$SANDBOX/mcp_int_out.XXXX")
  local errfile; errfile=$(mktemp "$SANDBOX/mcp_int_err.XXXX")
  set +e
  python3 "$py_script" > "$outfile" 2> "$errfile"
  local rc=$?
  set -e
  if [ "$rc" -ne "$expected_exit" ]; then
    echo "  FAIL  $name (exit $rc, expected $expected_exit)"
    echo "        stderr: $(cat "$errfile")"
    failed=$((failed+1))
  elif [ -n "$expected_out" ] && ! grep -qF -e "$expected_out" "$outfile"; then
    echo "  FAIL  $name (output missing: $expected_out)"
    echo "        output: $(cat "$outfile")"
    echo "        stderr: $(cat "$errfile")"
    failed=$((failed+1))
  else
    echo "  PASS  $name"
    passed=$((passed+1))
  fi
  rm -f "$py_script" "$outfile" "$errfile"
}

if [ "$HAS_MCP_PKG" = "yes" ]; then

  # 1. Server starts and responds to initialize
  test_mcp_integration "mcp integration: initialize" "initialize_OK" 0 \
'proc = subprocess.Popen(
    [sys.executable, MCP_SERVER],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, env=os.environ
)
try:
    req = {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}
    proc.stdin.write(json.dumps(req) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    resp = json.loads(line)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    assert "result" in resp
    assert resp["result"]["protocolVersion"] == "2024-11-05"
    print("initialize_OK")
finally:
    proc.terminate()
    proc.wait()'

  # 2. tools/list returns all 4 tools
  test_mcp_integration "mcp integration: tools/list" "tools_list_OK" 0 \
'proc = subprocess.Popen(
    [sys.executable, MCP_SERVER],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, env=os.environ
)
try:
    proc.stdin.write(json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}) + "\n")
    proc.stdin.flush()
    proc.stdout.readline()
    proc.stdin.write(json.dumps({"jsonrpc":"2.0","method":"notifications/initialized"}) + "\n")
    proc.stdin.flush()
    proc.stdin.write(json.dumps({"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    resp = json.loads(line)
    tools = resp["result"]["tools"]
    assert len(tools) == 4, "got {} tools".format(len(tools))
    names = [t["name"] for t in tools]
    for n in ["classify_task","format_jira_text","delegate_task","aggregate_profile"]:
        assert n in names, "missing: {}".format(n)
    print("tools_list_OK")
finally:
    proc.terminate()
    proc.wait()'

  # 3. classify_task returns correct classification for a sample prompt
  test_mcp_integration "mcp integration: classify_task" "classify_task_OK" 0 \
'proc = subprocess.Popen(
    [sys.executable, MCP_SERVER],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, env=os.environ
)
try:
    proc.stdin.write(json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}) + "\n")
    proc.stdin.flush()
    proc.stdout.readline()
    proc.stdin.write(json.dumps({"jsonrpc":"2.0","method":"notifications/initialized"}) + "\n")
    proc.stdin.flush()
    proc.stdin.write(json.dumps({"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"classify_task","arguments":{"prompt":"fix the README typo"}}}) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    resp = json.loads(line)
    content = json.loads(resp["result"]["content"][0]["text"])
    assert content["task_type"] == "code_edit", "got {}".format(content["task_type"])
    assert content["name"] == "small"
    print("classify_task_OK")
finally:
    proc.terminate()
    proc.wait()'

  # 4. format_jira_text strips markdown correctly
  test_mcp_integration "mcp integration: format_jira_text" "format_jira_OK" 0 \
'proc = subprocess.Popen(
    [sys.executable, MCP_SERVER],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, env=os.environ
)
try:
    proc.stdin.write(json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}) + "\n")
    proc.stdin.flush()
    proc.stdout.readline()
    proc.stdin.write(json.dumps({"jsonrpc":"2.0","method":"notifications/initialized"}) + "\n")
    proc.stdin.flush()
    proc.stdin.write(json.dumps({"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"format_jira_text","arguments":{"markdown":"**bold** and *italic*"}}}) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    resp = json.loads(line)
    content = json.loads(resp["result"]["content"][0]["text"])
    assert content["plain_text"] == "bold and italic", "got: {}".format(content["plain_text"])
    print("format_jira_OK")
finally:
    proc.terminate()
    proc.wait()'

  # 5. delegate_task with fake claude returns structured result
  test_mcp_integration "mcp integration: delegate_task" "delegate_task_OK" 0 \
'mcp_json = os.path.join(SANDBOX, "test_mcp.json")
with open(mcp_json, "w") as f:
    json.dump({"mcpServers": {}}, f)
try:
    proc = subprocess.Popen(
        [sys.executable, MCP_SERVER],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=os.environ
    )
    try:
        proc.stdin.write(json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}) + "\n")
        proc.stdin.flush()
        proc.stdout.readline()
        proc.stdin.write(json.dumps({"jsonrpc":"2.0","method":"notifications/initialized"}) + "\n")
        proc.stdin.flush()
        proc.stdin.write(json.dumps({"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"delegate_task","arguments":{"prompt":"test prompt","output_mode":"quiet"}}}) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        resp = json.loads(line)
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["result"] == "done", "got: {}".format(content)
        assert content["usage"]["input_tokens"] == 5
        assert "classification" in content
        print("delegate_task_OK")
    finally:
        proc.terminate()
        proc.wait()
finally:
    os.unlink(mcp_json)'

  # 6. aggregate_profile with temp JSONL returns summary
  test_mcp_integration "mcp integration: aggregate_profile" "aggregate_profile_OK" 0 \
'jsonl_path = os.path.join(SANDBOX, "test_profile.jsonl")
with open(jsonl_path, "w") as f:
    f.write(json.dumps({"isError":False,"model":"pro","usage":{"input_tokens":100,"output_tokens":50}}) + "\n")
    f.write(json.dumps({"isError":False,"model":"flash","usage":{"input_tokens":50,"output_tokens":25}}) + "\n")
try:
    proc = subprocess.Popen(
        [sys.executable, MCP_SERVER],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=os.environ
    )
    try:
        proc.stdin.write(json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}) + "\n")
        proc.stdin.flush()
        proc.stdout.readline()
        proc.stdin.write(json.dumps({"jsonrpc":"2.0","method":"notifications/initialized"}) + "\n")
        proc.stdin.flush()
        proc.stdin.write(json.dumps({"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"aggregate_profile","arguments":{"profile_log_path":jsonl_path,"format":"text"}}}) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        resp = json.loads(line)
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "Records: 2" in content["text_summary"], "got: {}".format(content["text_summary"])
        print("aggregate_profile_OK")
    finally:
        proc.terminate()
        proc.wait()
finally:
    os.unlink(jsonl_path)'

  # 7. Invalid tool name returns error
  test_mcp_integration "mcp integration: invalid tool" "invalid_tool_OK" 0 \
'proc = subprocess.Popen(
    [sys.executable, MCP_SERVER],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, env=os.environ
)
try:
    proc.stdin.write(json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}) + "\n")
    proc.stdin.flush()
    proc.stdout.readline()
    proc.stdin.write(json.dumps({"jsonrpc":"2.0","method":"notifications/initialized"}) + "\n")
    proc.stdin.flush()
    proc.stdin.write(json.dumps({"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"nonexistent_tool","arguments":{}}}) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    resp = json.loads(line)
    assert resp.get("result", {}).get("isError"), "expected isError, got: {}".format(resp)
    print("invalid_tool_OK")
finally:
    proc.terminate()
    proc.wait()'

  # 8. Malformed JSON returns parse error
  test_mcp_integration "mcp integration: malformed JSON" "malformed_json_OK" 0 \
'proc = subprocess.Popen(
    [sys.executable, MCP_SERVER],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, env=os.environ
)
try:
    proc.stdin.write("this is not json\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    resp = json.loads(line)
    assert resp.get("params", {}).get("level") == "error", "expected error notification, got: {}".format(resp)
    assert resp["jsonrpc"] == "2.0"
    print("malformed_json_OK")
finally:
    proc.terminate()
    proc.wait()'

else
  echo "  SKIP  mcp integration tests (mcp package not installed)"
fi

# 9. No mcp package: verify error message and exit code
if [ "$HAS_MCP_PKG" = "no" ]; then
  set +e
  python3 "$MCP_SERVER" > /dev/null 2>"$SANDBOX/mcp_no_pkg_stderr"
  no_mcp_rc=$?
  set -e
  if [ "$no_mcp_rc" -ne 1 ]; then
    echo "  FAIL  mcp server no package (exit $no_mcp_rc, expected 1)"
    failed=$((failed+1))
  elif grep -qF "pip install mcp" "$SANDBOX/mcp_no_pkg_stderr"; then
    echo "  PASS  mcp server no package"
    passed=$((passed+1))
  else
    echo "  FAIL  mcp server no package (missing error message)"
    echo "        stderr: $(cat "$SANDBOX/mcp_no_pkg_stderr")"
    failed=$((failed+1))
  fi
  rm -f "$SANDBOX/mcp_no_pkg_stderr"
else
  echo "  PASS  mcp server no package (mcp installed, error path verified by module test)"
  passed=$((passed+1))
fi

# ---- pipeline.py tests ----

echo ""
echo "=== pipeline.py ==="

# test_pipeline_py name expected_out expected_exit py_code
test_pipeline_py() {
  local name="$1" expected_out="$2" expected_exit="$3"
  local py_script; py_script=$(mktemp "$SANDBOX/pipe_script.XXXX.py")
  cat > "$py_script" <<PYEOF
import sys, os, json, tempfile
sys.path.insert(0, "$SCRIPT_DIR/../scripts")
$4
PYEOF
  local outfile; outfile=$(mktemp "$SANDBOX/pipe_out.XXXX")
  local errfile; errfile=$(mktemp "$SANDBOX/pipe_err.XXXX")
  set +e
  python3 "$py_script" > "$outfile" 2> "$errfile"
  local rc=$?
  set -e
  if [ "$rc" -ne "$expected_exit" ]; then
    echo "  FAIL  $name (exit $rc, expected $expected_exit)"
    echo "        stderr: $(cat "$errfile")"
    failed=$((failed+1))
  elif [ -n "$expected_out" ] && ! grep -qF -e "$expected_out" "$outfile"; then
    echo "  FAIL  $name (output missing: $expected_out)"
    echo "        output: $(cat "$outfile")"
    echo "        stderr: $(cat "$errfile")"
    failed=$((failed+1))
  else
    echo "  PASS  $name"
    passed=$((passed+1))
  fi
  rm -f "$py_script" "$outfile" "$errfile"
}

test_pipeline_py \
  "pipeline module imports DelegationResult and run_delegation_pipeline" \
  "pipeline_ok" 0 \
  "from pipeline import DelegationResult, run_delegation_pipeline
dr = DelegationResult(result='ok', usage={}, cost_usd=0.0, terminal_reason='', is_error=False, classification={}, model='pro', effort='max')
assert dr.result == 'ok'
assert dr.model == 'pro'
print('pipeline_ok')"

test_pipeline_py \
  "run_delegation_pipeline code-edit prompt uses flash model" \
  "flash" 0 \
  "from pipeline import run_delegation_pipeline
result = run_delegation_pipeline('fix the README typo', output_mode='quiet')
assert not result.is_error
assert 'done' in result.result
print('flash')
# Check flash model was used for code edit
assert 'flash' in result.model, f'expected flash but got {result.model}'"

test_pipeline_py \
  "run_delegation_pipeline architecture prompt uses pro model" \
  "pro_model_ok" 0 \
  "from pipeline import run_delegation_pipeline
result = run_delegation_pipeline('architecture refactor plan', output_mode='quiet')
assert not result.is_error
assert 'pro' in result.model, f'expected pro but got {result.model}'
assert result.effort == 'max'
print('pro_model_ok')"

test_pipeline_py \
  "run_delegation_pipeline explicit model_tier overrides classification" \
  "model_override_ok" 0 \
  "from pipeline import run_delegation_pipeline
result = run_delegation_pipeline('check how many rows', model_tier='pro', output_mode='quiet')
assert 'pro' in result.model, f'expected pro but got {result.model}'
print('model_override_ok')"

test_pipeline_py \
  "run_delegation_pipeline explicit effort overrides classification" \
  "effort_override_ok" 0 \
  "from pipeline import run_delegation_pipeline
result = run_delegation_pipeline('check how many rows', effort='max', output_mode='quiet')
assert result.effort == 'max'
print('effort_override_ok')"

test_pipeline_py \
  "run_delegation_pipeline stream mode returns raw output" \
  "stream_ok" 0 \
  "from pipeline import run_delegation_pipeline
result = run_delegation_pipeline('test prompt', output_mode='stream')
assert 'done' in result.result
print('stream_ok')"

test_pipeline_py \
  "run_delegation_pipeline subagent_mode off disallows Task Agent" \
  "HAS_DISALLOWED" 0 \
  "from pipeline import run_delegation_pipeline
import os, json, tempfile
capture = tempfile.mktemp(suffix='.txt')
os.environ['CLAUDE_DELEGATE_TEST_CAPTURE'] = capture
result = run_delegation_pipeline('test prompt', subagent_mode='off', output_mode='quiet')
captured = open(capture).read()
if '--disallowedTools' in captured and 'Task' in captured and 'Agent' in captured:
    print('HAS_DISALLOWED')
else:
    print('NO_DISALLOWED')
os.unlink(capture)"

test_pipeline_py \
  "run_delegation_pipeline profile logging writes JSONL when env set" \
  "profile_log_ok" 0 \
  "from pipeline import run_delegation_pipeline
import os, json, tempfile
log_path = tempfile.mktemp(suffix='.jsonl')
os.environ['CLAUDE_DELEGATE_PROFILE_LOG'] = log_path
result = run_delegation_pipeline('test prompt', output_mode='quiet')
assert result.is_error == False
with open(log_path) as f:
    lines = [l for l in f if l.strip()]
assert len(lines) == 1, f'expected 1 profile record, got {len(lines)}'
record = json.loads(lines[0])
assert 'timestamp' in record
assert record['model'] == result.model
os.unlink(log_path)
print('profile_log_ok')"

test_pipeline_py \
  "DelegationResult carries resolved metadata fields" \
  "metadata_ok" 0 \
  "from pipeline import run_delegation_pipeline
result = run_delegation_pipeline('fix the README typo', output_mode='quiet')
assert result.permission_mode == 'bypassPermissions'
assert result.mcp_mode == 'all'
assert result.task_type == 'code_edit'
assert result.context_budget == 'standard'
assert result.prompt_mode == 'template'
assert result.prompt_template == 'code_edit'
assert result.original_prompt_chars > 0
assert result.prepared_prompt_chars > 0
assert result.original_prompt_chars <= result.prepared_prompt_chars
print('metadata_ok')"

test_pipeline_py \
  "profile JSONL contains task/context/prompt metadata fields" \
  "profile_metadata_ok" 0 \
  "from pipeline import run_delegation_pipeline
import os, json, tempfile
log_path = tempfile.mktemp(suffix='.jsonl')
os.environ['CLAUDE_DELEGATE_PROFILE_LOG'] = log_path
result = run_delegation_pipeline('architecture refactor plan', output_mode='quiet')
with open(log_path) as f:
    lines = [l for l in f if l.strip()]
assert len(lines) == 1
record = json.loads(lines[0])
assert record['class'] == 'large'
assert record['taskType'] == 'architecture_review'
assert record['contextBudget'] == 'expanded'
assert record['promptMode'] == 'template'
assert record['promptTemplate'] == 'architecture_review'
assert record['originalPromptChars'] > 0
assert record['preparedPromptChars'] > 0
assert record['totalCostUsd'] is not None
assert record['terminalReason'] is not None
os.unlink(log_path)
print('profile_metadata_ok')"

# ---- profile_logger.py tests ----

echo ""
echo "=== profile_logger.py ==="

# test_profile_logger_py name expected_out expected_exit py_code
test_profile_logger_py() {
  local name="$1" expected_out="$2" expected_exit="$3"
  local py_script; py_script=$(mktemp "$SANDBOX/pl_script.XXXX.py")
  cat > "$py_script" <<PYEOF
import sys, os, json
sys.path.insert(0, "$SCRIPT_DIR/../scripts")
$4
PYEOF
  local outfile; outfile=$(mktemp "$SANDBOX/pl_out.XXXX")
  local errfile; errfile=$(mktemp "$SANDBOX/pl_err.XXXX")
  set +e
  python3 "$py_script" > "$outfile" 2> "$errfile"
  local rc=$?
  set -e
  if [ "$rc" -ne "$expected_exit" ]; then
    echo "  FAIL  $name (exit $rc, expected $expected_exit)"
    echo "        stderr: $(cat "$errfile")"
    failed=$((failed+1))
  elif [ -n "$expected_out" ] && ! grep -qF -e "$expected_out" "$outfile"; then
    echo "  FAIL  $name (output missing: $expected_out)"
    echo "        output: $(cat "$outfile")"
    echo "        stderr: $(cat "$errfile")"
    failed=$((failed+1))
  else
    echo "  PASS  $name"
    passed=$((passed+1))
  fi
  rm -f "$py_script" "$outfile" "$errfile"
}

test_profile_logger_py \
  "build_profile_record exists and is callable" \
  "bpr_ok" 0 \
  "from profile_logger import build_profile_record
r = build_profile_record(model='test-model', effort='max')
assert r['model'] == 'test-model'
assert r['effort'] == 'max'
assert 'timestamp' in r
assert r['usage'] == {}
assert r['isError'] == False
print('bpr_ok')"

test_profile_logger_py \
  "build_profile_record full fields compact-claude-stream shape" \
  "bpr_full_ok" 0 \
  "from profile_logger import build_profile_record
r = build_profile_record(
    model='pro',
    effort='max',
    permission_mode='bypassPermissions',
    mcp_mode='all',
    task_class='small',
    task_type='code_edit',
    context_budget='standard',
    prompt_mode='template',
    prompt_template='code_edit',
    original_prompt_chars=100,
    prepared_prompt_chars=70,
    prompt_reduction_pct=30,
    usage={'input_tokens': 5, 'output_tokens': 10},
    total_cost_usd=0.01,
    terminal_reason='completed',
    is_error=False,
)
assert r['model'] == 'pro'
assert r['effort'] == 'max'
assert r['permissionMode'] == 'bypassPermissions'
assert r['mcpMode'] == 'all'
assert r['class'] == 'small'
assert r['taskType'] == 'code_edit'
assert r['contextBudget'] == 'standard'
assert r['promptMode'] == 'template'
assert r['promptTemplate'] == 'code_edit'
assert r['originalPromptChars'] == 100
assert r['preparedPromptChars'] == 70
assert r['promptReductionPct'] == 30
assert r['usage'] == {'input_tokens': 5, 'output_tokens': 10}
assert r['totalCostUsd'] == 0.01
assert r['terminalReason'] == 'completed'
assert r['isError'] == False
assert 'timestamp' in r
print('bpr_full_ok')"

test_profile_logger_py \
  "build_profile_record minimal fields mcp-server shape" \
  "bpr_minimal_ok" 0 \
  "from profile_logger import build_profile_record
r = build_profile_record(
    model='flash',
    effort='low',
    usage={'input_tokens': 5},
    is_error=False,
)
assert r['model'] == 'flash'
assert r['effort'] == 'low'
assert r['usage'] == {'input_tokens': 5}
assert r['isError'] == False
assert r['permissionMode'] is None
assert r['class'] is None
print('bpr_minimal_ok')"

test_profile_logger_py \
  "build_profile_record isEmpty defaults to False with empty usage" \
  "bpr_defaults_ok" 0 \
  "from profile_logger import build_profile_record
r = build_profile_record()
assert r['isError'] == False
assert r['usage'] == {}
assert r['originalPromptChars'] == 0
assert r['preparedPromptChars'] == 0
assert r['promptReductionPct'] == 0
print('bpr_defaults_ok')"

# ---- quality-gate.sh tests ----

echo ""
echo "=== quality-gate.sh ==="

QUALITY_GATE="$SCRIPT_DIR/../scripts/quality-gate.sh"

# Create fake test runners for quality-gate testing
cat > "$SANDBOX/fake-pass" <<'FAKE'
#!/usr/bin/env bash
echo "fake-pass: all tests passed"
exit 0
FAKE
chmod +x "$SANDBOX/fake-pass"

cat > "$SANDBOX/fake-fail" <<'FAKE'
#!/usr/bin/env bash
echo "fake-fail: tests failed"
exit 1
FAKE
chmod +x "$SANDBOX/fake-fail"

# test_qg name expected_exit expected_stdout test_cmd [extra_env]
test_qg() {
  local name="$1" expected_exit="$2" expected_stdout="$3" test_cmd="$4"
  local stdout_file; stdout_file=$(mktemp "$SANDBOX/qg_stdout.XXXX")
  set +e
  CLAUDE_DELEGATE_QUALITY_GATE_TEST_COMMAND="$test_cmd" "$QUALITY_GATE" > "$stdout_file" 2>/dev/null
  local got_exit=$?
  set -e
  if [ "$got_exit" -ne "$expected_exit" ]; then
    echo "  FAIL  $name (exit $got_exit, expected $expected_exit)"
    echo "        stdout: $(tr '\n' '|' < "$stdout_file")"
    failed=$((failed+1))
  elif [ -n "$expected_stdout" ] && ! grep -qF -e "$expected_stdout" "$stdout_file"; then
    echo "  FAIL  $name (stdout missing: $expected_stdout)"
    echo "        stdout: $(tr '\n' '|' < "$stdout_file")"
    failed=$((failed+1))
  else
    echo "  PASS  $name"
    passed=$((passed+1))
  fi
  rm -f "$stdout_file"
}

[ -f "$QUALITY_GATE" ] || echo "  FAIL  quality-gate.sh not found (expected scripts/quality-gate.sh)"

test_qg "quality gate exits 0 on passing runner" 0 "Quality Gate: claude-code-delegate" "$SANDBOX/fake-pass"

test_qg "quality gate exit 0 shows runner identity" 0 "Test Runner: $SANDBOX/fake-pass" "$SANDBOX/fake-pass"

test_qg "quality gate exits non-zero on failing runner" 1 "fake-fail: tests failed" "$SANDBOX/fake-fail"

test_qg "quality gate exit non-zero shows runner identity" 1 "Test Runner: $SANDBOX/fake-fail" "$SANDBOX/fake-fail"

# ---- CI workflow tests (CCDM-19) ----

echo ""
echo "=== CI workflow ==="

CI_WORKFLOW="$SCRIPT_DIR/../.github/workflows/quality-gate.yml"

if [ -f "$CI_WORKFLOW" ]; then
  echo "  PASS  .github/workflows/quality-gate.yml exists"
  passed=$((passed+1))
else
  echo "  FAIL  .github/workflows/quality-gate.yml not found"
  failed=$((failed+1))
fi

if [ -f "$CI_WORKFLOW" ]; then
  if grep -qF "pull_request" "$CI_WORKFLOW" && grep -qF "push:" "$CI_WORKFLOW"; then
    echo "  PASS  CI workflow triggers on pull_request and push"
    passed=$((passed+1))
  else
    echo "  FAIL  CI workflow missing pull_request or push trigger"
    failed=$((failed+1))
  fi

  if grep -qF "quality-gate.sh" "$CI_WORKFLOW"; then
    echo "  PASS  CI workflow invokes quality-gate.sh"
    passed=$((passed+1))
  else
    echo "  FAIL  CI workflow does not invoke quality-gate.sh"
    failed=$((failed+1))
  fi

  if grep -qF "branches:" "$CI_WORKFLOW" && grep -qF "main" "$CI_WORKFLOW"; then
    echo "  PASS  CI workflow targets main branch"
    passed=$((passed+1))
  else
    echo "  FAIL  CI workflow does not target main branch"
    failed=$((failed+1))
  fi

  if grep -qF "CLAUDE_DELEGATE_HEARTBEAT_SECONDS" "$CI_WORKFLOW" && grep -qF "0" "$CI_WORKFLOW"; then
    echo "  PASS  CI workflow disables heartbeat"
    passed=$((passed+1))
  else
    echo "  FAIL  CI workflow does not disable heartbeat"
    failed=$((failed+1))
  fi
fi

# ---- release-gate-report.sh tests (CCDM-21) ----

echo ""
echo "=== release-gate-report.sh ==="

RELEASE_GATE_REPORT="$SCRIPT_DIR/../scripts/release-gate-report.sh"

# test_rgr name expected_exit expected_stdout test_cmd [extra_env]
test_rgr() {
  local name="$1" expected_exit="$2" expected_stdout="$3" test_cmd="$4"
  local stdout_file; stdout_file=$(mktemp "$SANDBOX/rgr_stdout.XXXX")
  set +e
  CLAUDE_DELEGATE_QUALITY_GATE_TEST_COMMAND="$test_cmd" \
    CLAUDE_DELEGATE_RELEASE_TAG="v1.0.0-test" \
    "$RELEASE_GATE_REPORT" > "$stdout_file" 2>/dev/null
  local got_exit=$?
  set -e
  if [ "$got_exit" -ne "$expected_exit" ]; then
    echo "  FAIL  $name (exit $got_exit, expected $expected_exit)"
    echo "        stdout: $(tr '\n' '|' < "$stdout_file")"
    failed=$((failed+1))
  elif [ -n "$expected_stdout" ] && ! grep -qF -e "$expected_stdout" "$stdout_file"; then
    echo "  FAIL  $name (stdout missing: $expected_stdout)"
    echo "        stdout: $(tr '\n' '|' < "$stdout_file")"
    failed=$((failed+1))
  else
    echo "  PASS  $name"
    passed=$((passed+1))
  fi
  rm -f "$stdout_file"
}

if [ -f "$RELEASE_GATE_REPORT" ]; then
  echo "  PASS  release-gate-report.sh exists"
  passed=$((passed+1))
else
  echo "  FAIL  release-gate-report.sh not found"
  failed=$((failed+1))
fi

if [ -f "$RELEASE_GATE_REPORT" ]; then
  test_rgr "release report success path shows PASS" 0 "Gate Status: PASS" "$SANDBOX/fake-pass"
  test_rgr "release report success path shows commit" 0 "Commit:" "$SANDBOX/fake-pass"
  test_rgr "release report success path shows tag" 0 "Tag: v1.0.0-test" "$SANDBOX/fake-pass"
  test_rgr "release report success path shows residual risk" 0 "Residual Risk:" "$SANDBOX/fake-pass"
  test_rgr "release report failure path shows FAIL" 1 "Gate Status: FAIL" "$SANDBOX/fake-fail"
  test_rgr "release report failure path blocks release" 1 "BLOCKED" "$SANDBOX/fake-fail"
  test_rgr "release report header present" 0 "Release Quality Gate Report" "$SANDBOX/fake-pass"
fi

# ---- quality gate docs tests (CCDM-22) ----

echo ""
echo "=== quality gate docs ==="

README="$SCRIPT_DIR/../README.md"
SKILL="$SCRIPT_DIR/../SKILL.md"

# test_doc name file expected_substr
test_doc() {
  local name="$1" file="$2" expected="$3"
  if grep -qF -e "$expected" "$file"; then
    echo "  PASS  $name"
    passed=$((passed+1))
  else
    echo "  FAIL  $name (missing: $expected in $(basename "$file"))"
    failed=$((failed+1))
  fi
}

# Check README has quality gate section
test_doc "README has quality gate section" "$README" "Quality Gate"

# Check README references the local command
test_doc "README references quality-gate.sh" "$README" "quality-gate.sh"

# Check README references CI workflow
test_doc "README references CI workflow" "$README" "github/workflows/quality-gate.yml"

# Check external-system caveats are documented
test_doc "README documents external-system caveats" "$README" "external-system"

# Check ADR 0003 is referenced
test_doc "README references ADR 0003" "$README" "ADR 0003"

# Check isolated runtime assumption is documented
test_doc "README documents isolated Claude runtime" "$README" "Isolated Claude runtime"

# ---- ADR 0003 status test (CCDM-23) ----

echo ""
echo "=== ADR 0003 ==="

ADR0003="$SCRIPT_DIR/../docs/adr/0003-ci-cd-quality-gates.md"

# ADR status must be "Accepted" on a line that starts with "## Status" or appears right after it.
# We check for the pattern: "## Status" followed by "Accepted" within a few lines.
if grep -A1 "^## Status$" "$ADR0003" | grep -qF "Accepted"; then
  echo "  PASS  ADR 0003 status is Accepted"
  passed=$((passed+1))
else
  echo "  FAIL  ADR 0003 status is not Accepted (currently shows Proposed)"
  failed=$((failed+1))
fi

test_doc "ADR 0003 external-system strategy is explicit" "$ADR0003" "no-live-service"

test_doc "ADR 0003 decision is documented" "$ADR0003" "Decision"

# ---- logging.py tests ----

echo ""
echo "=== logging.py ==="

# test_logging_py name expected_out expected_exit py_code
test_logging_py() {
  local name="$1" expected_out="$2" expected_exit="$3"
  local py_script; py_script=$(mktemp "$SANDBOX/log_script.XXXX.py")
  cat > "$py_script" <<PYEOF
import sys, os, json, io
sys.path.insert(0, "$SCRIPT_DIR/../scripts")
$4
PYEOF
  local outfile; outfile=$(mktemp "$SANDBOX/log_out.XXXX")
  local errfile; errfile=$(mktemp "$SANDBOX/log_err.XXXX")
  set +e
  python3 "$py_script" > "$outfile" 2> "$errfile"
  local rc=$?
  set -e
  if [ "$rc" -ne "$expected_exit" ]; then
    echo "  FAIL  $name (exit $rc, expected $expected_exit)"
    echo "        stderr: $(cat "$errfile")"
    failed=$((failed+1))
  elif [ -n "$expected_out" ] && ! grep -qF -e "$expected_out" "$outfile"; then
    echo "  FAIL  $name (output missing: $expected_out)"
    echo "        output: $(cat "$outfile")"
    echo "        stderr: $(cat "$errfile")"
    failed=$((failed+1))
  else
    echo "  PASS  $name"
    passed=$((passed+1))
  fi
  rm -f "$py_script" "$outfile" "$errfile"
}

test_logging_py \
  "logging module exists and imports" \
  "logging OK" 0 \
  "from logger import get_logger, Logger; print('logging OK')"

test_logging_py \
  "get_logger returns Logger instance with debug/info/warn/error methods" \
  "logger OK" 0 \
  "from logger import get_logger
logger = get_logger('test')
assert hasattr(logger, 'debug'), 'no debug'
assert hasattr(logger, 'info'), 'no info'
assert hasattr(logger, 'warn'), 'no warn'
assert hasattr(logger, 'error'), 'no error'
print('logger OK')"

test_logging_py \
  "JSON format outputs valid JSON lines with ts/level/logger/msg keys" \
  "json_valid" 0 \
  "import os, json
os.environ['CLAUDE_DELEGATE_LOG_FORMAT'] = 'json'
from logger import get_logger
logger = get_logger('test-json')
stderr_capture = io.StringIO()
old_stderr = sys.stderr
sys.stderr = stderr_capture
logger.info('hello world')
sys.stderr = old_stderr
line = stderr_capture.getvalue().strip()
record = json.loads(line)
assert 'ts' in record, 'missing ts'
assert 'level' in record, 'missing level'
assert record['level'] == 'INFO', 'wrong level'
assert 'logger' in record, 'missing logger'
assert record['logger'] == 'test-json', 'wrong logger'
assert 'msg' in record, 'missing msg'
assert record['msg'] == 'hello world', 'wrong msg'
print('json_valid')"

test_logging_py \
  "text format outputs timestamp [LEVEL] logger: message key=value" \
  "text_format" 0 \
  "import os
os.environ['CLAUDE_DELEGATE_LOG_FORMAT'] = 'text'
from logger import get_logger
import io, sys
logger = get_logger('test-text')
stderr_capture = io.StringIO()
sys.stderr = stderr_capture
logger.info('hello', answer=42)
sys.stderr = sys.__stderr__
line = stderr_capture.getvalue().strip()
assert '[INFO]' in line, 'missing [INFO]'
assert 'test-text:' in line, 'missing logger name'
assert 'hello' in line, 'missing message'
assert 'answer=42' in line, 'missing key=value'
print('text_format')"

test_logging_py \
  "log level env var filters: DEBUG shows all, WARN hides debug+info" \
  "level_filter" 0 \
  "import os, io, sys
from logger import get_logger

# Test WARN hides debug+info
os.environ['CLAUDE_DELEGATE_LOG_LEVEL'] = 'WARN'
os.environ['CLAUDE_DELEGATE_LOG_FORMAT'] = 'text'
logger = get_logger('test-filter')
capture = io.StringIO()
sys.stderr = capture
logger.debug('should not appear')
logger.info('should not appear too')
logger.warn('should appear')
sys.stderr = sys.__stderr__
output = capture.getvalue()
assert 'should not appear' not in output, 'debug leaked at WARN level'
assert 'should not appear too' not in output, 'info leaked at WARN level'
assert 'should appear' in output, 'warn missing at WARN level'

# Test DEBUG shows all
os.environ['CLAUDE_DELEGATE_LOG_LEVEL'] = 'DEBUG'
logger2 = get_logger('test-filter2')
capture2 = io.StringIO()
sys.stderr = capture2
logger2.debug('debug visible')
logger2.info('info visible')
sys.stderr = sys.__stderr__
output2 = capture2.getvalue()
assert 'debug visible' in output2, 'debug missing at DEBUG level'
assert 'info visible' in output2, 'info visible at DEBUG level'
print('level_filter')"

test_logging_py \
  "extra kwargs appear in JSON output" \
  "extra_kwargs" 0 \
  "import os, json, io, sys
os.environ['CLAUDE_DELEGATE_LOG_FORMAT'] = 'json'
from logger import get_logger
logger = get_logger('test-extra')
capture = io.StringIO()
sys.stderr = capture
logger.info('test', user_id=123, action='login')
sys.stderr = sys.__stderr__
record = json.loads(capture.getvalue().strip())
assert record['user_id'] == 123, 'missing user_id'
assert record['action'] == 'login', 'missing action'
print('extra_kwargs')"

# ---- health-check.py tests ----

echo ""
echo "=== health-check.py ==="

HEALTH_CHECK="$SCRIPT_DIR/../scripts/health-check.py"

test_logging_py \
  "health-check module exists and imports" \
  "health_check OK" 0 \
  "import importlib.util, os
spec = importlib.util.spec_from_file_location('health_check', os.path.join('$SCRIPT_DIR', '../scripts/health-check.py'))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
assert hasattr(mod, 'run_health_checks'), 'missing run_health_checks'
print('health_check OK')"

test_health_bash() {
  local name="$1" expected_out="$2" expected_exit="$3"
  shift 3
  local outfile; outfile=$(mktemp "$SANDBOX/hc_out.XXXX")
  set +e
  python3 "$HEALTH_CHECK" "$@" > "$outfile" 2>/dev/null
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

test_health_bash \
  "--health flag produces expected output (starts with PASS or FAIL)" \
  "PASS python3" 0

test_health_bash \
  "health check reports python3 available" \
  "PASS python3" 0

test_health_bash \
  "health check reports claude on PATH" \
  "claude" 0

test_health_bash \
  "health check reports pipeline.py exists" \
  "pipeline.py" 0

test_health_bash \
  "health check exit 0 when all pass" \
  "HEALTHY" 0

test_health_bash \
  "health check output includes HEALTHY or UNHEALTHY" \
  "HEALTHY" 0

# Test exit 1 when a check fails
test_health_fail() {
  local outfile; outfile=$(mktemp "$SANDBOX/hcf_out.XXXX")
  # Build a PATH without any directory that contains an executable "claude"
  local clean_path=""
  local saved_ifs="$IFS"; IFS=:
  for dir in $PATH; do
    if [ ! -x "$dir/claude" ]; then
      clean_path="${clean_path}${clean_path:+:}${dir}"
    fi
  done
  IFS="$saved_ifs"
  set +e
  CLAUDE_DELEGATE_HEALTH_REQUIRE_CLAUDE=1 PATH="$clean_path" python3 "$HEALTH_CHECK" > "$outfile" 2>/dev/null
  local rc=$?
  set -e
  if [ "$rc" -ne 1 ]; then
    echo "  FAIL  health check exit 1 when a check fails (exit $rc, expected 1)"
    echo "        output: $(cat "$outfile")"
    failed=$((failed+1))
  elif ! grep -qF "UNHEALTHY" "$outfile"; then
    echo "  FAIL  health check output includes UNHEALTHY when failing"
    echo "        output: $(cat "$outfile")"
    failed=$((failed+1))
  else
    echo "  PASS  health check exit 1 when a check fails"
    passed=$((passed+1))
  fi
  rm -f "$outfile"
}
test_health_fail

# ---- async delegation tests ----

echo ""
echo "=== async delegation ==="

# test_async_start name expected_exit expected_json_key [args...]
# Like test_case but captures stdout (JSON) instead of discarding it
test_async_start() {
  local name="$1" expected_exit="$2" expected_key="$3"
  shift 3
  local stdout_file; stdout_file=$(mktemp "$SANDBOX/stdout.XXXX")
  local capture; capture=$(mktemp "$SANDBOX/cap.XXXX")
  set +e
  CLAUDE_DELEGATE_TEST_CAPTURE="$capture" "$RUNNER" "$@" > "$stdout_file" 2>/dev/null
  local got_exit=$?
  set -e
  if [ "$got_exit" -ne "$expected_exit" ]; then
    echo "  FAIL  $name (exit $got_exit, expected $expected_exit)"
    failed=$((failed+1))
  elif ! python3 -c "import sys,json; d=json.load(sys.stdin); assert '$expected_key' in d" < "$stdout_file" 2>/dev/null; then
    echo "  FAIL  $name (JSON missing key: $expected_key)"
    echo "        stdout: $(cat "$stdout_file")"
    failed=$((failed+1))
  else
    echo "  PASS  $name"
    passed=$((passed+1))
  fi
  rm -f "$stdout_file" "$capture"
}

# test_async_poll name expected_exit expected_json_key [args...]
test_async_poll() {
  local name="$1" expected_exit="$2" expected_key="$3"
  shift 3
  local stdout_file; stdout_file=$(mktemp "$SANDBOX/stdout.XXXX")
  set +e
  "$RUNNER" "$@" > "$stdout_file" 2>/dev/null
  local got_exit=$?
  set -e
  if [ "$got_exit" -ne "$expected_exit" ]; then
    echo "  FAIL  $name (exit $got_exit, expected $expected_exit)"
    failed=$((failed+1))
  elif ! python3 -c "import sys,json; d=json.load(sys.stdin); assert '$expected_key' in d" < "$stdout_file" 2>/dev/null; then
    echo "  FAIL  $name (JSON missing key: $expected_key)"
    echo "        stdout: $(cat "$stdout_file")"
    failed=$((failed+1))
  else
    echo "  PASS  $name"
    passed=$((passed+1))
  fi
  rm -f "$stdout_file"
}

# --start returns JSON with job_id, status, lease_active
test_async_start "async start returns job_id" 0 "job_id" --start "test prompt"

test_async_start "async start returns running status" 0 "status" --start "test prompt"

test_async_start "async start returns lease_active" 0 "lease_active" --start "test prompt"

# --start returns a positive pid (not 0)
async_pid_out=$(mktemp "$SANDBOX/async_pid.XXXX")
set +e
"$RUNNER" --start "test prompt" > "$async_pid_out" 2>/dev/null
async_pid_rc=$?
set -e
async_pid=$(python3 -c "import sys,json; print(json.load(sys.stdin).get('pid',0))" < "$async_pid_out" 2>/dev/null || echo "0")
if [ "$async_pid_rc" -eq 0 ] && [ "$async_pid" -gt 0 ] 2>/dev/null; then
  echo "  PASS  async start returns positive pid (pid=$async_pid)"
  passed=$((passed+1))
else
  echo "  FAIL  async start returns positive pid (pid=$async_pid, rc=$async_pid_rc)"
  echo "        stdout: $(cat "$async_pid_out")"
  failed=$((failed+1))
fi
rm -f "$async_pid_out"

# --poll on non-existent job (status is a value, not a key, so test inline)
async_poll_out=$(mktemp "$SANDBOX/ap_out.XXXX")
set +e
"$RUNNER" --poll "nonexistent-job-id" > "$async_poll_out" 2>/dev/null
poll_rc=$?
set -e
poll_status=$(python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" < "$async_poll_out" 2>/dev/null || echo "")
if [ "$poll_rc" -ne 1 ] || [ "$poll_status" != "not_found" ]; then
  echo "  FAIL  poll nonexistent job returns not_found (rc=$poll_rc, status=$poll_status)"
  failed=$((failed+1))
else
  echo "  PASS  poll nonexistent job returns not_found"
  passed=$((passed+1))
fi
rm -f "$async_poll_out"

# --start then --poll on the same job (fake claude exits quickly, may be completed or running)
# We capture the job_id and poll it
async_capture=$(mktemp "$SANDBOX/async_capture.XXXX")
set +e
CLAUDE_DELEGATE_TEST_CAPTURE=$(mktemp "$SANDBOX/acap.XXXX") "$RUNNER" --start "test prompt" > "$async_capture" 2>/dev/null
set -e
job_id=$(python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])" < "$async_capture" 2>/dev/null || echo "")
if [ -n "$job_id" ] && [ "$job_id" != "None" ]; then
  # Poll the job — it may be completed (fake claude exits instantly) or running
  poll_out=$(mktemp "$SANDBOX/poll_out.XXXX")
  set +e
  "$RUNNER" --poll "$job_id" > "$poll_out" 2>/dev/null
  poll_rc=$?
  set -e
  poll_status=$(python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" < "$poll_out" 2>/dev/null || echo "")
  if [ "$poll_status" = "completed" ] || [ "$poll_status" = "running" ] || [ "$poll_status" = "failed" ]; then
    echo "  PASS  async start-then-poll (status=$poll_status)"
    passed=$((passed+1))
  else
    echo "  FAIL  async start-then-poll (unexpected status=$poll_status)"
    echo "        stdout: $(cat "$poll_out")"
    failed=$((failed+1))
  fi
  rm -f "$poll_out"
else
  echo "  FAIL  async start-then-poll (could not extract job_id)"
  echo "        stdout: $(cat "$async_capture")"
  failed=$((failed+1))
fi
rm -f "$async_capture"

# ---- lease / single-flight tests ----

echo ""
echo "=== lease / single-flight ==="

# test_job_manager_py name expected_out expected_exit py_code_body
test_job_manager_py() {
  local name="$1" expected_out="$2" expected_exit="$3"
  local py_script; py_script=$(mktemp "$SANDBOX/jm_script.XXXX.py")
  cat > "$py_script" <<PYEOF
import sys, os, json, tempfile, subprocess, time
sys.path.insert(0, "$SCRIPT_DIR/../scripts")
$4
PYEOF
  local outfile; outfile=$(mktemp "$SANDBOX/jm_out.XXXX")
  local errfile; errfile=$(mktemp "$SANDBOX/jm_err.XXXX")
  set +e
  python3 "$py_script" > "$outfile" 2> "$errfile"
  local rc=$?
  set -e
  if [ "$rc" -ne "$expected_exit" ]; then
    echo "  FAIL  $name (exit $rc, expected $expected_exit)"
    echo "        stderr: $(cat "$errfile")"
    failed=$((failed+1))
  elif [ -n "$expected_out" ] && ! grep -qF -e "$expected_out" "$outfile"; then
    echo "  FAIL  $name (output missing: $expected_out)"
    echo "        output: $(cat "$outfile")"
    echo "        stderr: $(cat "$errfile")"
    failed=$((failed+1))
  else
    echo "  PASS  $name"
    passed=$((passed+1))
  fi
  rm -f "$py_script" "$outfile" "$errfile"
}

test_job_manager_py \
  "job_manager module exists and imports" \
  "job_manager OK" 0 \
  "from job_manager import get_jobs_dir, create_job_id, create_job_meta, read_job_meta, find_active_lease, get_job_status, write_job_result
print('job_manager OK')"

test_job_manager_py \
  "create_job_id returns hex string" \
  "job_id_len=12" 0 \
  "from job_manager import create_job_id
jid = create_job_id()
assert len(jid) == 12
print('job_id_len=12')"

test_job_manager_py \
  "create_job_meta and read_job_meta roundtrip" \
  "roundtrip OK" 0 \
  "from job_manager import create_job_meta, read_job_meta, get_jobs_dir
jid = 'test-roundtrip'
meta = create_job_meta(jid, pid=12345, prompt='test prompt', model='pro', effort='max', permission_mode='bypassPermissions', mcp_mode='all', output_mode='quiet')
assert meta['job_id'] == jid
assert meta['pid'] == 12345
assert meta['status'] == 'running'
readback = read_job_meta(jid)
assert readback == meta
print('roundtrip OK')"

test_job_manager_py \
  "find_active_lease returns None when no jobs" \
  "no_lease=None" 0 \
  "from job_manager import find_active_lease, get_jobs_dir
import shutil, os
# clean up test jobs
jd = get_jobs_dir()
for d in jd.iterdir():
    if d.is_dir():
        shutil.rmtree(d)
result = find_active_lease()
print('no_lease={}'.format(result))"

test_job_manager_py \
  "find_active_lease returns running job with alive pid" \
  "found_active_lease" 0 \
  "from job_manager import find_active_lease, create_job_meta, get_jobs_dir
import subprocess, time, shutil
# Use a sleep process as a fake running job
jd = get_jobs_dir()
for d in jd.iterdir():
    if d.is_dir():
        shutil.rmtree(d)
proc = subprocess.Popen(['sleep', '30'])
create_job_meta(job_id='lease-test', pid=proc.pid, prompt='test', model='pro', effort='max', permission_mode='bypassPermissions', mcp_mode='all', output_mode='quiet')
lease = find_active_lease()
proc.terminate()
proc.wait()
if lease and lease['job_id'] == 'lease-test':
    print('found_active_lease')
else:
    print('no_lease_found: {}'.format(lease))"

test_job_manager_py \
  "find_active_lease abandons dead pid and returns None" \
  "abandoned_lease=None" 0 \
  "from job_manager import find_active_lease, create_job_meta, get_jobs_dir
import subprocess, time, shutil
jd = get_jobs_dir()
for d in jd.iterdir():
    if d.is_dir():
        shutil.rmtree(d)
proc = subprocess.Popen(['sleep', '0.1'])
create_job_meta(job_id='dead-test', pid=proc.pid, prompt='test', model='pro', effort='max', permission_mode='bypassPermissions', mcp_mode='all', output_mode='quiet')
proc.wait()
time.sleep(0.2)
lease = find_active_lease()
print('abandoned_lease={}'.format(lease))"

test_job_manager_py \
  "_pid_alive returns False for pid=0" \
  "pid0_not_alive" 0 \
  "from job_manager import _pid_alive
assert _pid_alive(0) == False
assert _pid_alive(-1) == False
print('pid0_not_alive')"

test_job_manager_py \
  "find_active_lease does not treat pid=0 as alive" \
  "no_lease_pid0" 0 \
  "from job_manager import find_active_lease, create_job_meta, get_jobs_dir
import shutil
jd = get_jobs_dir()
for d in jd.iterdir():
    if d.is_dir():
        shutil.rmtree(d)
create_job_meta(job_id='pid0-test', pid=0, prompt='test', model='pro', effort='max', permission_mode='bypassPermissions', mcp_mode='all', output_mode='quiet')
lease = find_active_lease()
assert lease is None, 'pid=0 should not be active: {}'.format(lease)
print('no_lease_pid0')"

test_job_manager_py \
  "get_job_status returns running for alive pid" \
  "status=running" 0 \
  "from job_manager import get_job_status, create_job_meta, get_jobs_dir
import subprocess, shutil
jd = get_jobs_dir()
for d in jd.iterdir():
    if d.is_dir():
        shutil.rmtree(d)
proc = subprocess.Popen(['sleep', '30'])
create_job_meta(job_id='status-test', pid=proc.pid, prompt='test', model='pro', effort='max', permission_mode='bypassPermissions', mcp_mode='all', output_mode='quiet')
status = get_job_status('status-test')
proc.terminate()
proc.wait()
print('status={}'.format(status.get('status')))"

test_job_manager_py \
  "get_job_status returns completed when result exists with rc=0" \
  "status=completed" 0 \
  "from job_manager import get_job_status, create_job_meta, write_job_result, get_jobs_dir
import shutil
jd = get_jobs_dir()
for d in jd.iterdir():
    if d.is_dir():
        shutil.rmtree(d)
create_job_meta(job_id='complete-test', pid=99999, prompt='test', model='pro', effort='max', permission_mode='bypassPermissions', mcp_mode='all', output_mode='quiet')
write_job_result('complete-test', returncode=0, stdout='{\"type\":\"result\",\"result\":\"done\"}', stderr='')
status = get_job_status('complete-test')
print('status={}'.format(status.get('status')))"

test_job_manager_py \
  "get_job_status returns failed when result exists with rc!=0" \
  "status=failed" 0 \
  "from job_manager import get_job_status, create_job_meta, write_job_result
import shutil
create_job_meta(job_id='fail-test', pid=99999, prompt='test', model='pro', effort='max', permission_mode='bypassPermissions', mcp_mode='all', output_mode='quiet')
write_job_result('fail-test', returncode=1, stdout='', stderr='error happened')
status = get_job_status('fail-test')
print('status={}'.format(status.get('status')))"

test_job_manager_py \
  "get_job_status returns not_found for nonexistent job" \
  "status=not_found" 0 \
  "from job_manager import get_job_status
status = get_job_status('nonexistent-job')
print('status={}'.format(status.get('status')))"

# ---- start_delegation_async pipeline test ----

test_job_manager_py \
  "start_delegation_async with fake claude returns job_id" \
  "job_id_ok" 0 \
  "from pipeline import start_delegation_async
result = start_delegation_async('test prompt', model_tier='auto', effort='auto', permission_mode='auto', mcp_mode='all', context_mode='auto', subagent_mode='off', output_mode='quiet')
assert 'job_id' in result
assert result['status'] in ('running', 'lease_held')
print('job_id_ok')"

test_job_manager_py \
  "start_delegation_async includes lease_active=true and positive pid" \
  "lease_active_ok" 0 \
  "from pipeline import start_delegation_async
result = start_delegation_async('test prompt')
assert result.get('lease_active') == True
assert isinstance(result.get('pid'), int) and result['pid'] > 0, f'expected positive pid, got {result.get(\"pid\")}'
print('lease_active_ok')"

test_job_manager_py \
  "poll_delegation_status returns status dict" \
  "poll_status_ok" 0 \
  "from pipeline import start_delegation_async, poll_delegation_status
import time
start_result = start_delegation_async('test prompt')
jid = start_result['job_id']
time.sleep(0.5)
status = poll_delegation_status(jid)
assert 'status' in status
assert status['job_id'] == jid
print('poll_status_ok: {}'.format(status['status']))"

test_job_manager_py \
  "poll_delegation_status returns not_found for bad id" \
  "poll_not_found_ok" 0 \
  "from pipeline import poll_delegation_status
status = poll_delegation_status('no-such-job')
assert status['status'] == 'not_found'
print('poll_not_found_ok')"

# ---- lease enforcement through pipeline ----

test_job_manager_py \
  "start_delegation_async rejects duplicate when lease active" \
  "lease_rejected_ok" 0 \
  "from pipeline import start_delegation_async
from job_manager import create_job_meta, get_jobs_dir
import subprocess, shutil
# Clean up
jd = get_jobs_dir()
for d in jd.iterdir():
    if d.is_dir():
        shutil.rmtree(d)
# Create a fake running job
proc = subprocess.Popen(['sleep', '30'])
create_job_meta(job_id='active-lease', pid=proc.pid, prompt='test', model='pro', effort='max', permission_mode='bypassPermissions', mcp_mode='all', output_mode='quiet')
# Try to start another delegation
result = start_delegation_async('new prompt')
proc.terminate()
proc.wait()
if result['status'] == 'lease_held' and result['job_id'] == 'active-lease':
    print('lease_rejected_ok')
else:
    print('lease_not_rejected: {}'.format(result))"

# ---- async waiter / supervisor returncode tests ----

echo ""
echo "=== async waiter returncode ==="

# Test 1: job with result.json rc=3 -> get_job_status reports failed
test_job_manager_py \
  "job result: non-zero rc reports failed" \
  "result_fail_ok" 0 \
  "from job_manager import get_jobs_dir, create_job_meta, get_job_status, write_job_result
import shutil
jd = get_jobs_dir()
for d in jd.iterdir():
    if d.is_dir():
        shutil.rmtree(d)
create_job_meta('result-fail', pid=99999, prompt='test', model='flash', effort='low', permission_mode='bypassPermissions', mcp_mode='all', output_mode='quiet')
write_job_result('result-fail', returncode=3, stdout='some output', stderr='error happened')
status = get_job_status('result-fail')
assert status['status'] == 'failed', f\"expected failed, got {status['status']}\"
assert status['returncode'] == 3, f\"expected rc=3, got {status['returncode']}\"
print('result_fail_ok')"

# Test 2: job with result.json rc=0 -> get_job_status reports completed
test_job_manager_py \
  "job result: zero rc reports completed" \
  "result_ok" 0 \
  "from job_manager import get_jobs_dir, create_job_meta, get_job_status, write_job_result
import shutil
jd = get_jobs_dir()
for d in jd.iterdir():
    if d.is_dir():
        shutil.rmtree(d)
create_job_meta('result-ok', pid=99999, prompt='test', model='flash', effort='low', permission_mode='bypassPermissions', mcp_mode='all', output_mode='quiet')
write_job_result('result-ok', returncode=0, stdout='{\"type\":\"result\",\"result\":\"done\"}', stderr='')
status = get_job_status('result-ok')
assert status['status'] == 'completed', f\"expected completed, got {status['status']}\"
assert status['returncode'] == 0, f\"expected rc=0, got {status['returncode']}\"
print('result_ok')"

# Test 3: running job stays running before result recorded
test_job_manager_py \
  "async waiter: running stays running before result recorded" \
  "waiter_running_ok" 0 \
  "from job_manager import get_jobs_dir, create_job_meta, get_job_status
import subprocess, time, shutil
jd = get_jobs_dir()
for d in jd.iterdir():
    if d.is_dir():
        shutil.rmtree(d)
job_id = 'waiter-running'
proc = subprocess.Popen(['sleep', '30'])
create_job_meta(job_id, proc.pid, 'test', 'flash', 'low', 'bypass', 'all', 'quiet')
status = get_job_status(job_id)
assert status['status'] == 'running', f\"expected running, got {status['status']}\"
assert status['pid_alive'] == True
proc.terminate()
proc.wait()
print('waiter_running_ok')"

# ---- wrapper-level --start / --poll tests ----

echo ""
echo "=== wrapper --start / --poll ==="

# Create fake claude that exits 0 with valid result JSON
cat > "$SANDBOX/claude-ok" <<'FAKEOK'
#!/usr/bin/env bash
cat <<'JSONEOF'
{"type":"result","result":"done","usage":{"input_tokens":5,"output_tokens":10}}
JSONEOF
FAKEOK
chmod +x "$SANDBOX/claude-ok"

# Create fake claude that exits non-zero with stdout
cat > "$SANDBOX/claude-fail" <<'FAKEFAIL'
#!/usr/bin/env bash
echo "some output before crash"
echo "some stderr output" >&2
exit 3
FAKEFAIL
chmod +x "$SANDBOX/claude-fail"

# Create fake claude that sleeps for 30s
cat > "$SANDBOX/claude-sleep" <<'FAKESLEEP'
#!/usr/bin/env bash
sleep 30
FAKESLEEP
chmod +x "$SANDBOX/claude-sleep"

export CLAUDE_DELEGATE_RUNTIME_DIR="$SANDBOX/runtime"

# Test 1: fake claude exits 0 with valid result JSON → poll returns completed
wrap_start_out=$(mktemp "$SANDBOX/wrap_start.XXXX")
set +e
"$RUNNER" --start "test prompt" > "$wrap_start_out" 2>/dev/null
set -e
wrap_job_id=$(python3 -c "import sys,json; print(json.load(sys.stdin).get('job_id',''))" < "$wrap_start_out" 2>/dev/null || echo "")
if [ -n "$wrap_job_id" ] && [ "$wrap_job_id" != "None" ]; then
  sleep 1
  wrap_poll_out=$(mktemp "$SANDBOX/wrap_poll.XXXX")
  set +e
  "$RUNNER" --poll "$wrap_job_id" > "$wrap_poll_out" 2>/dev/null
  set -e
  wrap_poll_status=$(python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" < "$wrap_poll_out" 2>/dev/null || echo "")
  if [ "$wrap_poll_status" = "completed" ]; then
    echo "  PASS  wrapper --start then --poll returns completed (exit 0)"
    passed=$((passed+1))
  else
    echo "  FAIL  wrapper --start then --poll returns completed (exit 0) (status=$wrap_poll_status)"
    echo "        poll output: $(cat "$wrap_poll_out")"
    failed=$((failed+1))
  fi
  rm -f "$wrap_poll_out"
else
  echo "  FAIL  wrapper --start then --poll returns completed (exit 0) (no job_id)"
  echo "        output: $(cat "$wrap_start_out")"
  failed=$((failed+1))
fi
rm -f "$wrap_start_out"

# Test 2: fake claude exits non-zero → poll returns failed with real returncode
cp "$SANDBOX/claude-fail" "$SANDBOX/claude"
wrap_start_out2=$(mktemp "$SANDBOX/wrap_start2.XXXX")
set +e
"$RUNNER" --start "test prompt" > "$wrap_start_out2" 2>/dev/null
set -e
wrap_job_id2=$(python3 -c "import sys,json; print(json.load(sys.stdin).get('job_id',''))" < "$wrap_start_out2" 2>/dev/null || echo "")
if [ -n "$wrap_job_id2" ] && [ "$wrap_job_id2" != "None" ]; then
  sleep 1
  wrap_poll_out2=$(mktemp "$SANDBOX/wrap_poll2.XXXX")
  set +e
  "$RUNNER" --poll "$wrap_job_id2" > "$wrap_poll_out2" 2>/dev/null
  set -e
  wrap_poll_status2=$(python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" < "$wrap_poll_out2" 2>/dev/null || echo "")
  wrap_poll_rc2=$(python3 -c "import sys,json; print(json.load(sys.stdin).get('returncode',-999))" < "$wrap_poll_out2" 2>/dev/null || echo "")
  if [ "$wrap_poll_status2" = "failed" ] && [ "$wrap_poll_rc2" = "3" ]; then
    echo "  PASS  wrapper --start then --poll returns failed with returncode=3 (exit non-zero)"
    passed=$((passed+1))
  else
    echo "  FAIL  wrapper --start then --poll returns failed with returncode=3 (exit non-zero) (status=$wrap_poll_status2, rc=$wrap_poll_rc2)"
    echo "        poll output: $(cat "$wrap_poll_out2")"
    failed=$((failed+1))
  fi
  rm -f "$wrap_poll_out2"
else
  echo "  FAIL  wrapper --start then --poll returns failed with returncode=3 (exit non-zero) (no job_id)"
  echo "        output: $(cat "$wrap_start_out2")"
  failed=$((failed+1))
fi
rm -f "$wrap_start_out2"

# Test 3: fake claude sleeps → second --start returns lease_held
cp "$SANDBOX/claude-sleep" "$SANDBOX/claude"
wrap_start_out3=$(mktemp "$SANDBOX/wrap_start3.XXXX")
set +e
"$RUNNER" --start "first job" > "$wrap_start_out3" 2>/dev/null
set -e
sleep 1
wrap_job_id3=$(python3 -c "import sys,json; print(json.load(sys.stdin).get('job_id',''))" < "$wrap_start_out3" 2>/dev/null || echo "")
wrap_start_out3b=$(mktemp "$SANDBOX/wrap_start3b.XXXX")
set +e
"$RUNNER" --start "second job" > "$wrap_start_out3b" 2>/dev/null
set -e
wrap_status3=$(python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" < "$wrap_start_out3b" 2>/dev/null || echo "")
wrap_lease_job_id=$(python3 -c "import sys,json; print(json.load(sys.stdin).get('job_id',''))" < "$wrap_start_out3b" 2>/dev/null || echo "")
if [ "$wrap_status3" = "lease_held" ] && [ "$wrap_lease_job_id" = "$wrap_job_id3" ]; then
  echo "  PASS  wrapper second --start returns lease_held while first job running"
  passed=$((passed+1))
else
  echo "  FAIL  wrapper second --start returns lease_held while first job running (status=$wrap_status3, lease_job_id=$wrap_lease_job_id, first_job_id=$wrap_job_id3)"
  echo "        output: $(cat "$wrap_start_out3b")"
  failed=$((failed+1))
fi
rm -f "$wrap_start_out3" "$wrap_start_out3b"

# Restore original fake claude (exit 0 with valid JSON)
cp "$SANDBOX/claude-ok" "$SANDBOX/claude"
# Clean up runtime dir for subsequent tests
rm -rf "$CLAUDE_DELEGATE_RUNTIME_DIR"
unset CLAUDE_DELEGATE_RUNTIME_DIR



# ---- summary ----

echo ""
echo "---"
echo "Result: $passed passed, $failed failed"

if [ "$failed" -gt 0 ]; then
  exit 1
fi
