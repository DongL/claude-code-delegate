#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 [--pro|--flash] [--effort VALUE] [--quiet|--stream] [--bypass|--interactive] [--mcp MODE] [--full-context] [--allow-subagents] PROMPT [CLAUDE_ARGS...]" >&2
  exit 2
fi

if [[ -n "${CLAUDE_DELEGATE_MODEL:-}" ]]; then
  model="$CLAUDE_DELEGATE_MODEL"
  model_explicit=1
else
  model="deepseek-v4-pro[1m]"
  model_explicit=0
fi

output_mode="${CLAUDE_DELEGATE_OUTPUT_MODE:-quiet}"
mcp_mode="${CLAUDE_DELEGATE_MCP_MODE:-all}"
context_mode="${CLAUDE_DELEGATE_CONTEXT_MODE:-auto}"
subagent_mode="${CLAUDE_DELEGATE_SUBAGENTS:-off}"
heartbeat_seconds="${CLAUDE_DELEGATE_HEARTBEAT_SECONDS:-30}"

if [[ -n "${CLAUDE_DELEGATE_PERMISSION_MODE:-}" ]]; then
  permission_mode="$CLAUDE_DELEGATE_PERMISSION_MODE"
  permission_explicit=1
else
  permission_mode="bypassPermissions"
  permission_explicit=0
fi

if [[ -n "${CLAUDE_DELEGATE_EFFORT:-}" ]]; then
  effort="$CLAUDE_DELEGATE_EFFORT"
  effort_explicit=1
else
  effort="max"
  effort_explicit=0
fi

while [[ $# -gt 0 ]]; do
  case "${1:-}" in
    --pro)
      model="deepseek-v4-pro[1m]"
      model_explicit=1
      shift
      ;;
    --flash)
      model="deepseek-v4-flash[1m]"
      model_explicit=1
      shift
      ;;
    --effort)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --effort" >&2
        exit 2
      fi
      effort="$2"
      effort_explicit=1
      shift 2
      ;;
    --quiet)
      output_mode="quiet"
      shift
      ;;
    --stream)
      output_mode="stream"
      shift
      ;;
    --bypass)
      permission_mode="bypassPermissions"
      permission_explicit=1
      shift
      ;;
    --interactive)
      permission_mode="acceptEdits"
      permission_explicit=1
      shift
      ;;
    --mcp)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --mcp (expected all, none, jira, linear, or sequential-thinking)" >&2
        exit 2
      fi
      mcp_mode="$2"
      shift 2
      ;;
    --full-context)
      context_mode="full"
      shift
      ;;
    --allow-subagents)
      subagent_mode="on"
      shift
      ;;
    --)
      shift
      break
      ;;
    *)
      break
      ;;
  esac
done

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 [--pro|--flash] [--effort VALUE] [--quiet|--stream] [--bypass|--interactive] [--mcp MODE] [--full-context] [--allow-subagents] PROMPT [CLAUDE_ARGS...]" >&2
  exit 2
fi

case "$output_mode" in
  quiet|stream) ;;
  *)
    echo "Invalid output mode: $output_mode (expected quiet or stream)" >&2
    exit 2
    ;;
esac

case "$mcp_mode" in
  all|none|jira|linear|sequential-thinking) ;;
  *)
    echo "Invalid MCP mode: $mcp_mode (expected all, none, jira, linear, or sequential-thinking)" >&2
    exit 2
    ;;
esac

case "$context_mode" in
  auto|full) ;;
  *)
    echo "Invalid context mode: $context_mode (expected auto or full)" >&2
    exit 2
    ;;
esac

case "$subagent_mode" in
  on|off) ;;
  *)
    echo "Invalid subagent mode: $subagent_mode (expected on or off)" >&2
    exit 2
    ;;
esac

case "$heartbeat_seconds" in
  ''|*[!0-9]*)
    echo "Invalid heartbeat seconds: $heartbeat_seconds (expected non-negative integer)" >&2
    exit 2
    ;;
esac

prompt="$1"
shift

# MAX_THINKING_TOKENS is the official Claude Code env var for thinking budget.
# On adaptive reasoning models, --effort is the primary control and
# MAX_THINKING_TOKENS is ignored unless CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING=1
# is set. Only export when explicitly overridden.
# Set to 0 to disable thinking entirely.
if [[ -n "${CLAUDE_DELEGATE_THINKING_TOKENS:-}" ]]; then
  export MAX_THINKING_TOKENS="$CLAUDE_DELEGATE_THINKING_TOKENS"
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cleanup_files=()

cleanup() {
  if [[ -n "${heartbeat_pid:-}" ]]; then
    kill "$heartbeat_pid" 2>/dev/null || true
    wait "$heartbeat_pid" 2>/dev/null || true
  fi
  if ((${#cleanup_files[@]})); then
    for file in "${cleanup_files[@]}"; do
      rm -f "$file"
    done
  fi
}
trap cleanup EXIT

heartbeat_pid=""

stop_heartbeat() {
  if [[ -n "$heartbeat_pid" ]]; then
    kill "$heartbeat_pid" 2>/dev/null || true
    wait "$heartbeat_pid" 2>/dev/null || true
    heartbeat_pid=""
  fi
}

start_heartbeat() {
  if [[ "$heartbeat_seconds" -eq 0 ]]; then
    return
  fi
  echo "Claude Code started: model=$model effort=$effort mcp=$mcp_mode mode=$output_mode" >&2
  (
    while sleep "$heartbeat_seconds"; do
      echo "Claude Code still running: model=$model effort=$effort mcp=$mcp_mode mode=$output_mode" >&2
    done
  ) &
  heartbeat_pid="$!"
}

prepared_prompt_file="$(mktemp "${TMPDIR:-/tmp}/claude-delegator-prompt.XXXXXX")"
adapter_env_file="$(mktemp "${TMPDIR:-/tmp}/claude-delegator-adapter.XXXXXX")"
cleanup_files+=("$prepared_prompt_file" "$adapter_env_file")

"$script_dir/delegation-adapter.py" \
  --prompt "$prompt" \
  --prompt-out "$prepared_prompt_file" \
  --env-out "$adapter_env_file" \
  --model "$model" \
  --effort "$effort" \
  --permission-mode "$permission_mode" \
  --model-explicit "$model_explicit" \
  --effort-explicit "$effort_explicit" \
  --permission-explicit "$permission_explicit" \
  --context-mode "$context_mode"

# shellcheck disable=SC1090
source "$adapter_env_file"

model="$CLAUDE_DELEGATE_ADAPTED_MODEL"
effort="$CLAUDE_DELEGATE_ADAPTED_EFFORT"
permission_mode="$CLAUDE_DELEGATE_ADAPTED_PERMISSION_MODE"
prompt="$(cat "$prepared_prompt_file")"

args=(
  claude
  -p
  --model "$model"
  --effort "$effort"
  --permission-mode "$permission_mode"
)

if [[ "$subagent_mode" == "off" ]]; then
  args+=(--disallowedTools Task Agent)
fi

mcp_args=()
case "$mcp_mode" in
  all)
    ;;
  none)
    mcp_args=(--strict-mcp-config --mcp-config '{"mcpServers":{}}')
    ;;
  jira|linear|sequential-thinking)
    source_mcp_config="${CLAUDE_DELEGATE_MCP_CONFIG_PATH:-$PWD/.mcp.json}"
    if [[ ! -f "$source_mcp_config" ]]; then
      echo "MCP mode '$mcp_mode' requires $source_mcp_config to exist" >&2
      exit 2
    fi
    selected_mcp_config="$(mktemp "${TMPDIR:-/tmp}/claude-delegator-mcp.XXXXXX")"
    cleanup_files+=("$selected_mcp_config")
    MCP_MODE="$mcp_mode" MCP_SOURCE="$source_mcp_config" MCP_OUT="$selected_mcp_config" node <<'NODE'
const fs = require("fs");

const mode = process.env.MCP_MODE;
const source = process.env.MCP_SOURCE;
const out = process.env.MCP_OUT;
const config = JSON.parse(fs.readFileSync(source, "utf8"));
const server = config.mcpServers?.[mode];

if (!server) {
  console.error(`MCP server '${mode}' not found in ${source}`);
  process.exit(2);
}

fs.writeFileSync(out, JSON.stringify({ mcpServers: { [mode]: server } }));
NODE
    mcp_args=(--strict-mcp-config --mcp-config "$selected_mcp_config")
    ;;
esac

if [[ "$output_mode" == "stream" ]]; then
  if ((${#mcp_args[@]})); then
    exec "${args[@]}" \
      "${mcp_args[@]}" \
      --verbose \
      --output-format stream-json \
      --include-partial-messages \
      "$@" \
      "$prompt"
  fi
  exec "${args[@]}" \
    --verbose \
    --output-format stream-json \
    --include-partial-messages \
    "$@" \
    "$prompt"
fi

output_file="$(mktemp "${TMPDIR:-/tmp}/claude-delegator-output.XXXXXX")"
cleanup_files+=("$output_file")

set +e
start_heartbeat
if ((${#mcp_args[@]})); then
  "${args[@]}" \
    "${mcp_args[@]}" \
    --output-format json \
    "$@" \
    "$prompt" >"$output_file"
else
  "${args[@]}" \
    --output-format json \
    "$@" \
    "$prompt" >"$output_file"
fi
claude_status=$?
stop_heartbeat
set -e

env \
  CLAUDE_DELEGATE_OBSERVED_MODEL="$model" \
  CLAUDE_DELEGATE_OBSERVED_EFFORT="$effort" \
  CLAUDE_DELEGATE_OBSERVED_PERMISSION_MODE="$permission_mode" \
  CLAUDE_DELEGATE_OBSERVED_MCP_MODE="$mcp_mode" \
  CLAUDE_DELEGATE_OBSERVED_CLASS="$CLAUDE_DELEGATE_SELECTED_CLASS" \
  CLAUDE_DELEGATE_OBSERVED_TASK_TYPE="$CLAUDE_DELEGATE_SELECTED_TASK_TYPE" \
  CLAUDE_DELEGATE_OBSERVED_CONTEXT_BUDGET="$CLAUDE_DELEGATE_CONTEXT_BUDGET" \
  CLAUDE_DELEGATE_OBSERVED_PROMPT_MODE="$CLAUDE_DELEGATE_PROMPT_MODE" \
  CLAUDE_DELEGATE_OBSERVED_PROMPT_TEMPLATE="$CLAUDE_DELEGATE_PROMPT_TEMPLATE" \
  CLAUDE_DELEGATE_ORIGINAL_PROMPT_CHARS="$CLAUDE_DELEGATE_ORIGINAL_PROMPT_CHARS" \
  CLAUDE_DELEGATE_PREPARED_PROMPT_CHARS="$CLAUDE_DELEGATE_PREPARED_PROMPT_CHARS" \
  CLAUDE_DELEGATE_PROMPT_REDUCTION_PCT="$CLAUDE_DELEGATE_PROMPT_REDUCTION_PCT" \
  CLAUDE_DELEGATE_OBSERVED_CWD="$PWD" \
  "$script_dir/compact-claude-stream.py" <"$output_file"
compact_status=$?

if [[ "$claude_status" -ne 0 ]]; then
  exit "$claude_status"
fi
exit "$compact_status"
