#!/usr/bin/env bash
# Test runner for claude-code-delegate scripts.
# No external packages required — uses fake claude on PATH.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNNER="$SCRIPT_DIR/../scripts/run-claude-code.sh"
COMPACT="$SCRIPT_DIR/../scripts/compact-claude-stream.py"
ADAPTER="$SCRIPT_DIR/../scripts/delegation-adapter.py"
AGGREGATOR="$SCRIPT_DIR/../scripts/aggregate-profile-log.py"

for f in "$RUNNER" "$COMPACT" "$ADAPTER" "$AGGREGATOR"; do
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

# test_case_absent name unexpected_capture_substr [args...]
test_case_absent() {
  local name="$1" unexpected_capture="$2"
  shift 2
  local capture; capture=$(mktemp "$SANDBOX/cap.XXXX")
  set +e
  CLAUDE_DELEGATOR_TEST_CAPTURE="$capture" "$RUNNER" "$@" >/dev/null 2>/dev/null
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

CLAUDE_DELEGATOR_MODEL="claude-sonnet-4-6" \
  test_case "CLAUDE_DELEGATOR_MODEL override" 0 "--model claude-sonnet-4-6" "test prompt"

CLAUDE_DELEGATOR_EFFORT="medium" \
  test_case "CLAUDE_DELEGATOR_EFFORT override" 0 "--effort medium" "test prompt"

CLAUDE_DELEGATOR_PERMISSION_MODE="bypassPermissions" \
  test_case "CLAUDE_DELEGATOR_PERMISSION_MODE override" 0 "--permission-mode bypassPermissions" "test prompt"

test_case "--bypass flag" 0 "--permission-mode bypassPermissions" --bypass "test prompt"

test_case "--interactive flag" 0 "--permission-mode acceptEdits" --interactive "test prompt"

# Explicit flag overrides env var
CLAUDE_DELEGATOR_PERMISSION_MODE="acceptEdits" \
  test_case "--bypass overrides env acceptEdits" 0 "--permission-mode bypassPermissions" --bypass "test prompt"

CLAUDE_DELEGATOR_PERMISSION_MODE="bypassPermissions" \
  test_case "--interactive overrides env bypassPermissions" 0 "--permission-mode acceptEdits" --interactive "test prompt"

# Quiet mode (default) writes JSON to temp file, pipes through compact script
test_case "quiet mode output-format json" 0 "--output-format json" "test prompt"

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

CLAUDE_DELEGATOR_OUTPUT_MODE="invalid" \
  test_exit "invalid output mode" 2 "test prompt"

CLAUDE_DELEGATOR_SUBAGENTS="invalid" \
  test_exit "invalid subagent mode" 2 "test prompt"

CLAUDE_DELEGATOR_HEARTBEAT_SECONDS="abc" \
  test_exit "invalid heartbeat seconds" 2 "test prompt"

CLAUDE_DELEGATOR_THINKING_TOKENS="0" \
  test_case "CLAUDE_DELEGATOR_THINKING_TOKENS export" 0 "MAX_THINKING_TOKENS:0" "test prompt"

test_case_absent "default mcp all no strict config" "--strict-mcp-config" "test prompt"

test_case "--mcp none strict config" 0 "--strict-mcp-config" --mcp none "test prompt"

test_case "--mcp none empty config" 0 '{"mcpServers":{}}' --mcp none "test prompt"

cat > "$SANDBOX/mcp.json" <<'JSON'
{
  "mcpServers": {
    "jira": { "command": "node", "args": ["jira.js"] },
    "linear": { "command": "node", "args": ["linear.js"] },
    "sequential-thinking": { "command": "node", "args": ["seq.js"] }
  }
}
JSON

CLAUDE_DELEGATOR_MCP_CONFIG_PATH="$SANDBOX/mcp.json" \
  test_case "--mcp jira strict config" 0 "--strict-mcp-config" --mcp jira "test prompt"

CLAUDE_DELEGATOR_MCP_CONFIG_PATH="$SANDBOX/mcp.json" \
  test_case "--mcp jira passes generated mcp-config" 0 "--mcp-config" --mcp jira "test prompt"

CLAUDE_DELEGATOR_MCP_MODE="none" \
  test_case "env mcp mode none" 0 "--strict-mcp-config" "test prompt"

test_exit "invalid mcp mode" 2 --mcp invalid "test prompt"

test_exit "no prompt exits 2" 2

# Test that --stream flag does NOT imply --quiet output format
test_case "stream flag adds verbose" 0 "--verbose" --stream "test prompt"

# Env override: CLAUDE_DELEGATOR_OUTPUT_MODE=stream
CLAUDE_DELEGATOR_OUTPUT_MODE="stream" \
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
  CLAUDE_DELEGATOR_TEST_CAPTURE="$capture" "$RUNNER" "$@" >/dev/null 2>"$stderr_capture"
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
  CLAUDE_DELEGATOR_TEST_CAPTURE="$capture" "$RUNNER" "$@" >/dev/null 2>"$stderr_capture"
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
test_stderr "heartbeat immediate start message" "Claude Code started" "test prompt"

CLAUDE_DELEGATOR_HEARTBEAT_SECONDS=0 \
  test_stderr_absent "heartbeat disabled with 0" "Claude Code started" "test prompt"

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
printf '%s' '{"type":"result","result":"ok"}' | CLAUDE_DELEGATOR_OBSERVED_MCP_MODE=jira "$COMPACT" > "$outfile" 2>/dev/null
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
  CLAUDE_DELEGATOR_OBSERVED_CLASS=tiny \
  CLAUDE_DELEGATOR_OBSERVED_TASK_TYPE=read_only_scan \
  CLAUDE_DELEGATOR_OBSERVED_CONTEXT_BUDGET=minimal \
  CLAUDE_DELEGATOR_OBSERVED_PROMPT_MODE=template \
  CLAUDE_DELEGATOR_OBSERVED_PROMPT_TEMPLATE=read_only_scan \
  CLAUDE_DELEGATOR_ORIGINAL_PROMPT_CHARS=100 \
  CLAUDE_DELEGATOR_PREPARED_PROMPT_CHARS=70 \
  CLAUDE_DELEGATOR_PROMPT_REDUCTION_PCT=30 \
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
  CLAUDE_DELEGATOR_PROFILE_LOG="$profile_log" \
  CLAUDE_DELEGATOR_OBSERVED_CLASS=small \
  CLAUDE_DELEGATOR_ORIGINAL_PROMPT_CHARS=10 \
  CLAUDE_DELEGATOR_PREPARED_PROMPT_CHARS=8 \
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

# ---- delegation-adapter.py tests ----

echo ""
echo "=== delegation-adapter.py ==="

# test_adapter name expected_in_prompt expected_not_in_prompt prompt_text args...
# Runs adapter directly and checks prompt-out content.
# Set expected_yes to '-' to skip positive check, expected_no to '-' to skip negative check.
test_adapter() {
  local name="$1" expected_yes="$2" expected_no="$3" prompt_text="$4"
  shift 4
  local prompt_out; prompt_out=$(mktemp "$SANDBOX/prompt_out.XXXX")
  local env_out; env_out=$(mktemp "$SANDBOX/env_out.XXXX")
  set +e
  python3 "$ADAPTER" \
    --prompt "$prompt_text" \
    --prompt-out "$prompt_out" \
    --env-out "$env_out" \
    "$@" >/dev/null 2>&1
  local rc=$?
  set -e
  if [ "$rc" -ne 0 ]; then
    echo "  FAIL  $name (exit $rc)"
    failed=$((failed+1))
    rm -f "$prompt_out" "$env_out"
    return
  fi
  if [ "$expected_yes" != "-" ] && ! grep -qF -e "$expected_yes" "$prompt_out"; then
    echo "  FAIL  $name (prompt-out missing: $expected_yes)"
    echo "        prompt_out: $(head -c 400 "$prompt_out")"
    failed=$((failed+1))
  elif [ "$expected_no" != "-" ] && grep -qF -e "$expected_no" "$prompt_out"; then
    echo "  FAIL  $name (prompt-out unexpectedly contains: $expected_no)"
    echo "        prompt_out: $(head -c 400 "$prompt_out")"
    failed=$((failed+1))
  else
    echo "  PASS  $name"
    passed=$((passed+1))
  fi
  rm -f "$prompt_out" "$env_out"
}

# Generate a long prompt that previously exceeded the old compact limit.
LONG_ADAPTER_PROMPT=$(python3 -c "
head = 'fix critical head start CRITICAL_HEAD_MARKER'
middle = ' CRITICAL_MIDDLE_MARKER '
tail = 'critical tail end CRITICAL_TAIL_END_MARKER'
filler = ' x' * 1000
print(head + filler + middle + filler + tail)
")

test_adapter \
  "adapter preserves long prompt head critical text" \
  "CRITICAL_HEAD_MARKER" "-" \
  "$LONG_ADAPTER_PROMPT" \
  --model "flash" --model-explicit "1" \
  --effort "medium" --effort-explicit "1" \
  --permission-mode "bypassPermissions" --permission-explicit "1"

test_adapter \
  "adapter preserves long prompt middle critical text" \
  "CRITICAL_MIDDLE_MARKER" "-" \
  "$LONG_ADAPTER_PROMPT" \
  --model "flash" --model-explicit "1" \
  --effort "medium" --effort-explicit "1" \
  --permission-mode "bypassPermissions" --permission-explicit "1"

test_adapter \
  "adapter preserves long prompt tail critical text" \
  "CRITICAL_TAIL_END_MARKER" "-" \
  "$LONG_ADAPTER_PROMPT" \
  --model "flash" --model-explicit "1" \
  --effort "medium" --effort-explicit "1" \
  --permission-mode "bypassPermissions" --permission-explicit "1"

test_adapter \
  "adapter does not truncate long original request" \
  "-" "truncated" \
  "$LONG_ADAPTER_PROMPT" \
  --model "flash" --model-explicit "1" \
  --effort "medium" --effort-explicit "1" \
  --permission-mode "bypassPermissions" --permission-explicit "1"

# Short prompt should remain unchanged (no truncation)
SHORT_ADAPTER_PROMPT="fix a typo in the readme END_CRITICAL"
test_adapter \
  "adapter keeps short prompt unchanged" \
  "END_CRITICAL" "truncated" \
  "$SHORT_ADAPTER_PROMPT" \
  --model "flash" --model-explicit "1" \
  --effort "medium" --effort-explicit "1" \
  --permission-mode "bypassPermissions" --permission-explicit "1"

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

# ---- summary ----

echo ""
echo "---"
echo "Result: $passed passed, $failed failed"

if [ "$failed" -gt 0 ]; then
  exit 1
fi
