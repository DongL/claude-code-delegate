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

By default the wrapper classifies the task and chooses model, effort, permission mode, and prompt shape. Unknown tasks keep the safe legacy defaults: `deepseek-v4-pro[1m]`, `max` effort, `bypassPermissions`, and compact `quiet` output. Adaptive reasoning is controlled by `--effort`; thinking tokens are only set when `CLAUDE_DELEGATOR_THINKING_TOKENS` is explicitly provided. The wrapper also disables Claude Code's built-in subagent tool by default and emits a quiet-mode heartbeat so long delegations do not look stuck. The wrapper does not shorten the original request sent to Claude Code; token savings should come from compacting Claude Code's output back to the orchestrator, not from dropping executor context.

All examples below use `resolve_delegator`. The resolver checks:
1. `CLAUDE_DELEGATOR_DIR` (explicit override)
2. `$HOME/.agents/skills/claude-code-delegate` (current Codex skill path)
3. `$HOME/.codex/skills/claude-code-delegate` (legacy Codex skill path)

Prefer the bundled wrapper to avoid flag drift.

### Delegation Suitability

Do not delegate tiny local inspection tasks unless the user explicitly asks to use Claude Code. If the task is read-only, deterministic, local to the current machine, and likely needs three or fewer shell commands, the orchestrator should run it directly and report the result. Delegation has leverage for implementation, multi-file edits, independent execution, Jira/MCP work, or tasks where Claude Code is specifically requested.

### Model

Two models available. The wrapper classifies the prompt first: tiny read-only and routine edit tasks route to **flash**, while debugging and architecture-heavy tasks route to **pro**. Unknown prompts fall back to **pro**.

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

Default is `bypassPermissions` (fully non-interactive — no permission prompts). Use `--interactive` for safer or debug sessions where you want to review tool commands before they execute:

```bash
# Default: fully non-interactive, no permission prompts
"$(resolve_delegator)" "$PROMPT"

# Interactive: auto-accepts file edits, prompts on tool commands
"$(resolve_delegator)" --interactive "$PROMPT"

# Explicit bypass (backwards-compatible alias for default)
"$(resolve_delegator)" --bypass "$PROMPT"
```

Or via environment variable (overrides default when no flag is supplied; explicit flags win when provided):

```bash
CLAUDE_DELEGATOR_PERMISSION_MODE=acceptEdits \
  "$(resolve_delegator)" "$PROMPT"
```

### Effort and Classification

The wrapper uses deterministic task classification when no explicit model/effort/permission override is supplied:

| Class | Typical task | Model | Effort | Context |
|-------|--------------|-------|--------|---------|
| `tiny` | read-only checks, counts, lists | flash | low | minimal |
| `small` | routine edits or Jira operations | flash | medium | standard |
| `medium` | debugging, traceback, regression work | pro | high | standard |
| `large` | architecture, refactor, migration, ADR work | pro | max | expanded |
| `default` | unknown/ambiguous task | pro | max | full prompt |

Explicit flags and env vars override classification:

```bash
"$(resolve_delegator)" --flash --effort medium "$PROMPT"

CLAUDE_DELEGATOR_EFFORT=max \
  "$(resolve_delegator)" "$PROMPT"
```

The compact output reports the selected class, task type, context budget, prompt mode, and template.

### Subagents and Heartbeat

Default delegation disables Claude Code's built-in `Task`/`Agent` subagent tool. This keeps the executor from spawning another local agent that can run for a long time while quiet mode buffers all output. Allow subagents only when the plan explicitly needs Claude Code to parallelize inside its own process:

```bash
"$(resolve_delegator)" --allow-subagents "$PROMPT"
```

Quiet mode prints progress to stderr immediately and every 30 seconds while Claude Code is still running. Set `CLAUDE_DELEGATOR_HEARTBEAT_SECONDS=0` to disable the heartbeat or another integer to change the interval.

### MCP Mode

Default MCP mode is `all`: Claude Code uses its normal project/user MCP configuration. Use selective MCP loading when a task only needs one server, or when unrelated MCP servers slow startup and inflate context.

```bash
# Default: use normal Claude Code MCP discovery
"$(resolve_delegator)" "$PROMPT"

# Disable all project/user MCP servers
"$(resolve_delegator)" --mcp none "$PROMPT"

# Load only one MCP server from .mcp.json
"$(resolve_delegator)" --mcp jira "$PROMPT"
"$(resolve_delegator)" --mcp linear "$PROMPT"
"$(resolve_delegator)" --mcp sequential-thinking "$PROMPT"
```

Supported modes are `all`, `none`, `jira`, `linear`, and `sequential-thinking`. `none` uses Claude Code's `--strict-mcp-config` with an empty MCP config. Specific server modes use `--strict-mcp-config` with a generated one-server config read from `.mcp.json`, or from `CLAUDE_DELEGATOR_MCP_CONFIG_PATH` when set.

Built-in Claude Code file and shell tools are not MCP servers, so `--mcp none` still allows normal implementation work. It only suppresses project/user MCP server loading.

Environment variable override:

```bash
CLAUDE_DELEGATOR_MCP_MODE=jira \
  "$(resolve_delegator)" "$PROMPT"
```

### Other overrides

```bash
CLAUDE_DELEGATOR_EFFORT=medium \           # default: max
CLAUDE_DELEGATOR_THINKING_TOKENS=0 \       # unset by default (--effort controls reasoning)
CLAUDE_DELEGATOR_OUTPUT_MODE=stream \      # default: quiet
CLAUDE_DELEGATOR_MCP_MODE=none \           # default: all
CLAUDE_DELEGATOR_CONTEXT_MODE=full \       # default: auto
CLAUDE_DELEGATOR_SUBAGENTS=on \            # default: off
CLAUDE_DELEGATOR_HEARTBEAT_SECONDS=15 \    # default: 30; 0 disables
CLAUDE_DELEGATOR_PROFILE_LOG=logs/delegation-profile.jsonl \
"$(resolve_delegator)" "$PROMPT"
```

### Context Envelope and Templates

For known task types, the wrapper wraps the full original prompt in a task-specific envelope before calling Claude Code. Current templates cover:

- `read_only_scan`
- `code_edit`
- `jira_operation`
- `architecture_review`

Each template preserves the full original request, task goal, allowed scope, constraints, and verification expectations. Unknown task types fall back to the original prompt. Use `--full-context` or `CLAUDE_DELEGATOR_CONTEXT_MODE=full` when debugging prompt adaptation.

### Profiling

Quiet output includes model, effort, permission mode, MCP mode, class, task type, context budget, prompt template, prompt character counts, usage tokens, cache-read tokens, cache-hit ratio when available, cost, and terminal reason. Prompt reduction is expected to be zero for normal templated prompts because the original request is preserved. Set `CLAUDE_DELEGATOR_PROFILE_LOG` to append the same non-secret metadata to JSONL for trend analysis. The bundled `scripts/aggregate-profile-log.py` reads these JSONL records and outputs a concise aggregate summary (plain text by default, `--json` for machine-readable).

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

Plain `claude -p` with default permissions can appear to hang because Claude Code is waiting on permission requests. The wrapper default `bypassPermissions` avoids this entirely by suppressing all permission prompts. For debugging sessions where you want to observe tool commands before they run, use the `--interactive` flag (which sets `acceptEdits` — auto-accepts file edits but prompts on Bash/tool commands).

Provider or org/auth access errors usually mean Claude Code is not currently switched to a provider that can serve `deepseek-v4-pro[1m]`, or the provider token in `~/.claude/settings.json` is malformed/expired. Confirm the configured `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, and model values without printing secret token contents.
