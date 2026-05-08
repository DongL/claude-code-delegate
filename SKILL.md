---
name: claude-code-delegate
description: Delegate an orchestrator-authored implementation plan to Claude Code, then review the resulting diff. Use when the user wants an orchestrator (e.g., Codex) to plan while Claude Code executes, or wants a plan-execute-review loop.
---

# Claude Code Delegate

## Contract

Use this workflow when the user wants an orchestrator to own planning/review while Claude Code performs implementation.

Required loop:

1. The orchestrator reads enough local context to make a concrete plan.
2. The orchestrator shows the implementation plan to the user before invoking Claude Code.
3. The orchestrator invokes Claude Code to execute that plan.
4. The orchestrator shows Claude Code's output to the user, including its changed-file list and verification results.
5. The orchestrator reviews Claude Code's diff and test output.
6. If needed, the orchestrator shows the targeted correction plan and invokes Claude Code again. Iterate until the diff is correct, surfacing results to the user after each pass so they can intervene if convergence stalls.
7. The orchestrator gives the user a concise final review with changed files, tests, and residual risk.

## Invocation

Always invoke Claude Code through the bundled wrapper. The orchestrator resolves the script path using this fallback chain — no mandatory setup step required:

```bash
resolve_delegator() {
  for dir in \
    "${CLAUDE_DELEGATOR_DIR:-}" \
    "$HOME/.agents/skills/claude-code-delegate" \
    "$HOME/.codex/skills/claude-code-delegate"
  do
    if [ -n "$dir" ] && [ -x "$dir/scripts/run-claude-code.sh" ]; then
      echo "$dir/scripts/run-claude-code.sh"
      return 0
    fi
  done
  echo "claude-code-delegate not found. Set CLAUDE_DELEGATOR_DIR or install the skill." >&2
  return 1
}
```

Then delegate via:

```bash
"$(resolve_delegator)" "$PROMPT"
```

By default the wrapper uses `deepseek-v4-pro[1m]`, `max` effort, `acceptEdits`, and compact `quiet` output for non-interactive plan execution. Adaptive reasoning is controlled by `--effort` (default `max`); thinking tokens are only set when `CLAUDE_DELEGATOR_THINKING_TOKENS` is explicitly provided.

All examples below use `resolve_delegator`. The resolver checks:
1. `CLAUDE_DELEGATOR_DIR` (explicit override)
2. `$HOME/.agents/skills/claude-code-delegate` (current Codex skill path)
3. `$HOME/.codex/skills/claude-code-delegate` (legacy Codex skill path)

Prefer the bundled wrapper to avoid flag drift.

### Delegation Suitability

Do not delegate tiny local inspection tasks unless the user explicitly asks to use Claude Code. If the task is read-only, deterministic, local to the current machine, and likely needs three or fewer shell commands, the orchestrator should run it directly and report the result. Delegation has leverage for implementation, multi-file edits, independent execution, Jira/MCP work, or tasks where Claude Code is specifically requested.

### Model

Two models available. Default is **pro** for complex plans; use **flash** for simple/high-throughput tasks.

Prefer the wrapper flags when switching models for one invocation:

```bash
# Use flash for this invocation:
"$(resolve_delegator)" --flash "$PROMPT"

# Use pro explicitly:
"$(resolve_delegator)" --pro "$PROMPT"
```

| Env var | Pro (default) | Flash |
|---------|---------------|-------|
| `CLAUDE_DELEGATOR_MODEL` | `deepseek-v4-pro[1m]` | `deepseek-v4-flash[1m]` |

```bash
# Env override is also supported:
CLAUDE_DELEGATOR_MODEL='deepseek-v4-flash[1m]' \
"$(resolve_delegator)" "$PROMPT"
```

### Output Mode

Default output mode is `quiet`: the wrapper asks Claude Code for final JSON output, pipes it through `compact-claude-stream.py`, and returns only the final result plus model, permission mode, usage, cost, and terminal status. This is the preferred mode for normal delegation because the orchestrator does not need to ingest every thinking or partial-message event.

Use `--stream` only when debugging Claude Code itself, diagnosing permission hangs, inspecting tool events, or preserving the raw stream is necessary:

```bash
# Compact output, default:
"$(resolve_delegator)" --flash "$PROMPT"

# Raw verbose stream-json output for debugging:
"$(resolve_delegator)" --flash --stream "$PROMPT"
```

### Permission Mode

Default is `acceptEdits` (auto-accepts file edits, prompts on tool commands). Use `--bypass` for fully non-interactive delegation:

```bash
"$(resolve_delegator)" --bypass "$PROMPT"
```

Or via environment variable:

```bash
CLAUDE_DELEGATOR_PERMISSION_MODE=bypassPermissions \
  "$(resolve_delegator)" "$PROMPT"
```

### Other overrides

```bash
CLAUDE_DELEGATOR_EFFORT=medium \           # default: max
CLAUDE_DELEGATOR_THINKING_TOKENS=0 \       # unset by default (--effort controls reasoning)
CLAUDE_DELEGATOR_OUTPUT_MODE=stream \      # default: quiet
"$(resolve_delegator)" "$PROMPT"
```

## Prompt Requirements

The prompt sent to Claude Code must include:

- The user's goal.
- The concrete plan to execute.
- Ownership boundaries: files/modules it may touch.
- A warning not to revert unrelated user changes.
- A recommendation to apply Karpathy-style coding guidelines if available (e.g., `/andrej-karpathy-skills:karpathy-guidelines` in Codex). Key principles: make surgical changes, prefer boring code, avoid overcomplication, surface assumptions, and define verifiable success criteria before starting.
- Verification commands to run.
- A request to report changed files and command results.

Before invoking Claude Code, show the user the concrete implementation plan the orchestrator authored. This should be concise but specific enough to make ownership boundaries and verification commands visible.

Invoke the wrapper directly without adding `timeout`. If Claude Code appears silent, re-run with `--stream` and inspect the wrapper's stream-json events before assuming it is stuck.

After Claude Code returns, show the user Claude Code's output. In quiet mode, show the compact final report. In stream mode, prefer the final result block when it is concise; if the stream output is noisy, summarize the key lines but preserve changed files, command results, errors, and any stated caveats.

## Review Requirements

After Claude Code returns:

1. Show Claude Code's output to the user before giving the orchestrator's review.
2. Run `git diff --stat` and inspect relevant diffs.
3. Run focused tests or checks.
4. If the diff is wrong or incomplete, show the targeted correction plan, then send a correction prompt using the same wrapper invocation. Repeat if needed, surfacing results after each pass.
5. Show the correction pass output before the next iteration or final review.
6. Do not accept unreviewed changes just because Claude Code completed successfully.

## Issue Tracker Integration

When delegating Jira or issue tracker work, apply Jira-safe plain text formatting (no Markdown). See [docs/jira-workflow.md](docs/jira-workflow.md) for details and the `scripts/jira-safe-text.py` utility.

## Known Failure Mode

Plain `claude -p` with default permissions can appear to hang because Claude Code is waiting on permission requests. The wrapper default `acceptEdits` only auto-accepts file edits and can still block Bash/tool commands such as `.venv/bin/python ...`; use the `--bypass` flag (or `CLAUDE_DELEGATOR_PERMISSION_MODE=bypassPermissions`) for fully non-interactive delegation.

Provider or org/auth access errors usually mean Claude Code is not currently switched to a provider that can serve `deepseek-v4-pro[1m]`, or the provider token in `~/.claude/settings.json` is malformed/expired. Confirm the configured `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, and model values without printing secret token contents.
