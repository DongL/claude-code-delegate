#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 [--pro|--flash] [--quiet|--stream] PROMPT [CLAUDE_ARGS...]" >&2
  exit 2
fi

model="${CLAUDE_DELEGATOR_MODEL:-deepseek-v4-pro[1m]}"
output_mode="${CLAUDE_DELEGATOR_OUTPUT_MODE:-quiet}"

while [[ $# -gt 0 ]]; do
  case "${1:-}" in
    --pro)
      model="deepseek-v4-pro[1m]"
      shift
      ;;
    --flash)
      model="deepseek-v4-flash[1m]"
      shift
      ;;
    --quiet)
      output_mode="quiet"
      shift
      ;;
    --stream)
      output_mode="stream"
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
  echo "Usage: $0 [--pro|--flash] [--quiet|--stream] PROMPT [CLAUDE_ARGS...]" >&2
  exit 2
fi

case "$output_mode" in
  quiet|stream) ;;
  *)
    echo "Invalid output mode: $output_mode (expected quiet or stream)" >&2
    exit 2
    ;;
esac

prompt="$1"
shift

effort="${CLAUDE_DELEGATOR_EFFORT:-max}"
permission_mode="${CLAUDE_DELEGATOR_PERMISSION_MODE:-acceptEdits}"

args=(
  claude
  -p
  --model "$model"
  --effort "$effort"
  --permission-mode "$permission_mode"
)

# MAX_THINKING_TOKENS is the official Claude Code env var for thinking budget.
# On adaptive reasoning models, --effort is the primary control and
# MAX_THINKING_TOKENS is ignored unless CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING=1
# is set. Only export when explicitly overridden.
# Set to 0 to disable thinking entirely.
if [[ -n "${CLAUDE_DELEGATOR_THINKING_TOKENS:-}" ]]; then
  export MAX_THINKING_TOKENS="$CLAUDE_DELEGATOR_THINKING_TOKENS"
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$output_mode" == "stream" ]]; then
  exec "${args[@]}" \
    --verbose \
    --output-format stream-json \
    --include-partial-messages \
    "$@" \
    "$prompt"
fi

output_file="$(mktemp "${TMPDIR:-/tmp}/claude-delegator-output.XXXXXX")"
trap 'rm -f "$output_file"' EXIT

set +e
"${args[@]}" \
  --output-format json \
  "$@" \
  "$prompt" >"$output_file"
claude_status=$?
set -e

env \
  CLAUDE_DELEGATOR_OBSERVED_MODEL="$model" \
  CLAUDE_DELEGATOR_OBSERVED_PERMISSION_MODE="$permission_mode" \
  CLAUDE_DELEGATOR_OBSERVED_CWD="$PWD" \
  "$script_dir/compact-claude-stream.py" <"$output_file"
compact_status=$?

if [[ "$claude_status" -ne 0 ]]; then
  exit "$claude_status"
fi
exit "$compact_status"
