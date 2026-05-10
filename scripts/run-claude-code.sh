#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 [--pro|--flash] [--effort VALUE] [--quiet|--stream] [--bypass|--interactive] [--mcp MODE] [--full-context] [--allow-subagents] PROMPT [CLAUDE_ARGS...]" >&2
  exit 2
fi

model_tier="auto"
output_mode="${CLAUDE_DELEGATE_OUTPUT_MODE:-quiet}"
mcp_mode="${CLAUDE_DELEGATE_MCP_MODE:-all}"
context_mode="${CLAUDE_DELEGATE_CONTEXT_MODE:-auto}"
subagent_mode="${CLAUDE_DELEGATE_SUBAGENTS:-off}"
heartbeat_seconds="${CLAUDE_DELEGATE_HEARTBEAT_SECONDS:-30}"

if [[ -n "${CLAUDE_DELEGATE_PERMISSION_MODE:-}" ]]; then
  permission_mode="$CLAUDE_DELEGATE_PERMISSION_MODE"
else
  permission_mode="bypassPermissions"
fi

if [[ -n "${CLAUDE_DELEGATE_EFFORT:-}" ]]; then
  effort="$CLAUDE_DELEGATE_EFFORT"
else
  effort="auto"
fi

while [[ $# -gt 0 ]]; do
  case "${1:-}" in
    --pro)
      model_tier="pro"
      shift
      ;;
    --flash)
      model_tier="flash"
      shift
      ;;
    --effort)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --effort" >&2
        exit 2
      fi
      effort="$2"
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
      shift
      ;;
    --interactive)
      permission_mode="acceptEdits"
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
if [[ -n "${CLAUDE_DELEGATE_THINKING_TOKENS:-}" ]]; then
  export MAX_THINKING_TOKENS="$CLAUDE_DELEGATE_THINKING_TOKENS"
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec python3 "$script_dir/run-pipeline.py" \
  "$prompt" \
  "$output_mode" \
  "$model_tier" \
  "$effort" \
  "$permission_mode" \
  "$mcp_mode" \
  "$context_mode" \
  "$subagent_mode" \
  "$@"
