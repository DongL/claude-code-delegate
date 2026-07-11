# Shell Wrapper CLI Reference

> Full CLI reference for `scripts/run-claude-code.sh`. For the orchestrator contract and MCP transport, see [SKILL.md](../SKILL.md).

## Quick Reference

| Flag | Env Var | Effect |
|------|---------|--------|
| `--pro` / `--flash` | `CLAUDE_DELEGATE_MODEL` | Model selection (pro: `deepseek-v4-pro[1m]`, flash: `deepseek-v4-flash[1m]`) |
| `--effort VALUE` | `CLAUDE_DELEGATE_EFFORT` | Reasoning budget (`low`/`medium`/`high`/`max`) |
| `--quiet` / `--stream` | `CLAUDE_DELEGATE_OUTPUT_MODE` | Output format (`quiet`: compact report, `stream`: raw JSON) |
| `--bypass` / `--interactive` | `CLAUDE_DELEGATE_PERMISSION_MODE` | Permission handling (`bypassPermissions`/`acceptEdits`) |
| `--mcp MODE` | `CLAUDE_DELEGATE_MCP_MODE` | MCP server loading (`all`/`none`/`jira`/`linear`/`sequential-thinking`) |
| `--full-context` | `CLAUDE_DELEGATE_CONTEXT_MODE` | Prompt adaptation (`auto`: template envelope, `full`: raw prompt) |
| `--allow-subagents` | `CLAUDE_DELEGATE_SUBAGENTS` | Subagent control (`on`/`off`, default `off`) |
| `--opencode` | `CLAUDE_DELEGATE_EXECUTOR` | Shorthand for `--executor opencode` |
| `--executor NAME` | `CLAUDE_DELEGATE_EXECUTOR` | Executor backend (`claude-code` default, or `opencode`) |
| `--start` | — | Launch delegation in background, return job_id JSON (async mode). |
| `--poll JOB_ID` | — | Poll async job status, return structured JSON. |
| `--change CHANGE_ID --task TASK_ID` | — | Delegate one task from a persisted change contract. Requires both flags together; only valid in default (synchronous) mode. |
| `--correction TEXT` | — | With `--change`/`--task`, append a correction-pass instruction and the previous run's result to the rendered task prompt. |
| `--project-root DIR` | — | With `--change`/`--task`, locate `.claude-delegate/changes/` under `DIR` instead of the current directory. Never forwarded to the executor. |
| `--health` | — | Run health checks (python3, claude, core scripts, runtime, mcp) and exit. Exit 0 = HEALTHY, 1 = UNHEALTHY. |
| *(none)* | `CLAUDE_DELEGATE_THINKING_TOKENS` | Explicit thinking token budget (unset by default) |
| *(none)* | `CLAUDE_DELEGATE_HEARTBEAT_SECONDS` | Heartbeat interval in seconds (default `30`, `0` disables) |
| *(none)* | `CLAUDE_DELEGATE_PROFILE_LOG` | JSONL path for profiling metadata |
| *(none)* | `CLAUDE_DELEGATE_DIR` | Install path override for resolver |
| *(none)* | `CLAUDE_DELEGATE_MCP_CONFIG_PATH` | Path to `.mcp.json` for single-server MCP mode |
| *(none)* | `CLAUDE_DELEGATE_LOG_LEVEL` | Log level: `DEBUG`, `INFO`, `WARN`, `ERROR` |
| *(none)* | `CLAUDE_DELEGATE_LOG_FORMAT` | Log format: `json` or `text` |
| *(none)* | `OPENCODE_BIN` | Explicit path to the OpenCode binary (auto-discovery falls back to PATH, then `~/.opencode/bin/opencode`, `~/.local/bin/opencode`, `/opt/homebrew/bin/opencode`, `/usr/local/bin/opencode`) |

## Delegation Suitability

Do not delegate tiny local inspection tasks unless the user explicitly asks to use a coding executor. If the task is read-only, deterministic, local to the current machine, and likely needs three or fewer shell commands, the orchestrator should run it directly and report the result. Delegation has leverage for implementation, multi-file edits, independent execution, Jira/MCP work, or tasks where Claude Code/OpenCode is specifically requested.

## Executor Backend

Claude Code is the default executor. OpenCode can be selected per invocation without changing the surrounding orchestration flow:

```bash
"$(resolve_delegator)" --opencode --flash "$PROMPT"
"$(resolve_delegator)" --executor opencode --qwen "$PROMPT"
```

The same selection is available through the environment:

```bash
CLAUDE_DELEGATE_EXECUTOR=opencode \
  "$(resolve_delegator)" --flash "$PROMPT"
```

This is the intended path when Claude Code is acting as the orchestrator and OpenCode is the implementation executor.

## Model

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
| `CLAUDE_DELEGATE_MODEL` | `deepseek-v4-pro[1m]` | `deepseek-v4-flash[1m]` |

```bash
# Env override is also supported:
CLAUDE_DELEGATE_MODEL='deepseek-v4-flash[1m]' \
"$(resolve_delegator)" "$PROMPT"
```

## Output Mode

Default output mode is `quiet`: the pipeline asks the selected executor for machine-readable output, parses it internally via `compact-claude-stream.py`, and returns only the final result plus model, permission mode, usage, cost, and terminal status. This is the preferred mode for normal delegation because the orchestrator does not need to ingest every thinking or partial-message event.

Use `--stream` only when debugging the executor itself, diagnosing permission hangs, inspecting tool events, or preserving the raw stream is necessary:

```bash
# Compact output, default:
"$(resolve_delegator)" --flash "$PROMPT"

# Raw verbose stream-json output for debugging:
"$(resolve_delegator)" --flash --stream "$PROMPT"
```

## Permission Mode

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
CLAUDE_DELEGATE_PERMISSION_MODE=acceptEdits \
  "$(resolve_delegator)" "$PROMPT"
```

## Effort and Classification

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

CLAUDE_DELEGATE_EFFORT=max \
  "$(resolve_delegator)" "$PROMPT"
```

The compact output reports the selected class, task type, context budget, prompt mode, and template.

## Subagents and Heartbeat

Default delegation disables Claude Code's built-in `Task`/`Agent` subagent tool. For OpenCode, default delegation does not pass an `--agent` flag; `--allow-subagents` adds `--agent build`. This keeps the executor from spawning another local agent unless the plan explicitly needs parallelization:

```bash
"$(resolve_delegator)" --allow-subagents "$PROMPT"
```

Quiet mode prints progress to stderr immediately and every 30 seconds while Claude Code is still running. Set `CLAUDE_DELEGATE_HEARTBEAT_SECONDS=0` to disable the heartbeat or another integer to change the interval.

## MCP Mode

Default MCP mode is `all`: Claude Code uses its normal project/user MCP configuration. OpenCode does not consume these Claude Code MCP flags; configure OpenCode tools through its own config files. Use selective MCP loading with the Claude Code backend when a task only needs one server, or when unrelated MCP servers slow startup and inflate context.

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

Supported modes are `all`, `none`, `jira`, `linear`, and `sequential-thinking`. `none` uses Claude Code's `--strict-mcp-config --mcp-config` with an empty MCP config. Specific server modes use `--strict-mcp-config --mcp-config` with a generated one-server config. When `CLAUDE_DELEGATE_MCP_CONFIG_PATH` is set, that file is used. Otherwise, the wrapper searches `~/.claude/mcp.json`, `~/.codex/mcp.json`, `.mcp.json`, and the skill directory `.mcp.json`, then picks the first config containing the requested server.

Built-in Claude Code file and shell tools are not MCP servers, so `--mcp none` still allows normal implementation work for the Claude Code backend. It only suppresses project/user MCP server loading.

Environment variable override:

```bash
CLAUDE_DELEGATE_MCP_MODE=jira \
  "$(resolve_delegator)" "$PROMPT"
```

## Async Delegation (Lease + Single-Flight)

Use `--start` to launch a delegation in the background and `--poll <job_id>` to check status. This mode solves a common failure pattern: the orchestrator assumes Claude Code is stuck, kills or abandons it, and starts a reduced correction plan — wasting tokens while the original invocation may still be working.

### Lease Semantics

- A running delegation job owns an **execution lease**. While a job is running, no second delegation may start.
- The orchestrator may only poll and report status. No retry, reduced correction plan, takeover, or second delegation is allowed until the original job reaches a terminal state.
- A long-running invocation is **not** evidence of stuckness by itself. Poll to check progress.

### Start a Delegation

```bash
"$(resolve_delegator)" --start "$PROMPT"
```

Output (JSON to stdout):

```json
{"status": "running", "job_id": "a1b2c3d4e5f6", "pid": 12345, "model": "deepseek-v4-pro[1m]", "effort": "max", "lease_active": true}
```

If another job is already running, the wrapper returns the active lease instead of starting a duplicate:

```json
{"status": "lease_held", "job_id": "existing-job-id", "pid": 12345, ...}
```

### Poll Status

```bash
"$(resolve_delegator)" --poll <job_id>
```

Output:

- **running** — `{"status": "running", "job_id": "...", "pid_alive": true, "stdout_bytes": ..., ...}`
- **completed** — `{"status": "completed", "result": "...", "usage": {...}, "cost_usd": ..., ...}`
- **failed** — `{"status": "failed", "returncode": 1, "stderr_tail": "...", ...}`
- **not_found** — `{"status": "not_found", "job_id": "..."}`

### Async Flags

| Flag | Env Var | Effect |
|------|---------|--------|
| `--start` | — | Launch delegation in background, return job_id JSON |
| `--poll JOB_ID` | — | Poll job status, return structured JSON |

All classification, envelope, model, effort, permission, MCP, and context flags work with `--start` as they do with synchronous delegation.

## Change Contracts

Use `--change CHANGE_ID --task TASK_ID` to delegate one task from a persisted change contract (`.claude-delegate/changes/<change-id>/change.json`) instead of passing a prompt on the command line. This is for work that spans multiple sessions or delegation passes — the goal, non-goals, requirements, tasks, dependencies, ownership boundaries, and verification commands are written once and referenced by ID from then on. See [README.md § Change contracts](../README.md#change-contracts-multi-session-orchestration) for the full workflow and [docs/prd/change-contracts.md](prd/change-contracts.md) for the design.

```bash
# Delegate a ready task (renders the full contract into a task prompt)
"$(resolve_delegator)" --change my-change --task task-001

# Correction pass after an orchestrator review rejects the result
"$(resolve_delegator)" --change my-change --task task-001 \
  --correction "Fix the off-by-one error."

# Look up the contract under a different project root than cwd
"$(resolve_delegator)" --change my-change --task task-001 --project-root /path/to/project
```

`--change`/`--task` must be used together and only in the default synchronous mode — combining either with `--start` or `--poll` exits 2. `--project-root` locates the contract files only; it is never forwarded to the executor. A task must be `pending` or `failed`, its change must be `active`, and every dependency must be `verified` (not merely `delegated`) before it is considered ready — an unready task exits non-zero with the specific blocker reason on stderr. Delegating a task only moves its status to `delegated` (or `failed` on executor error); reaching `verified` requires an explicit orchestrator review via `scripts/change-spec.py review` or the `record_change_task_review` MCP tool — never inferred from the executor's own report.

## Other overrides

```bash
CLAUDE_DELEGATE_EFFORT=medium \           # default: max
CLAUDE_DELEGATE_THINKING_TOKENS=0 \       # unset by default (--effort controls reasoning)
CLAUDE_DELEGATE_OUTPUT_MODE=stream \      # default: quiet
CLAUDE_DELEGATE_MCP_MODE=none \           # default: all
CLAUDE_DELEGATE_CONTEXT_MODE=full \       # default: auto
CLAUDE_DELEGATE_SUBAGENTS=on \            # default: off
CLAUDE_DELEGATE_HEARTBEAT_SECONDS=15 \    # default: 30; 0 disables
CLAUDE_DELEGATE_PROFILE_LOG=logs/delegation-profile.jsonl \
"$(resolve_delegator)" "$PROMPT"
```

## Context Envelope and Templates

For known task types, the wrapper wraps the full original prompt in a task-specific envelope before calling the selected executor. Current templates cover:

- `read_only_scan`
- `code_edit`
- `jira_operation`
- `architecture_review`

Each template preserves the full original request, task goal, allowed scope, constraints, and verification expectations. Unknown task types fall back to the original prompt. Use `--full-context` or `CLAUDE_DELEGATE_CONTEXT_MODE=full` when debugging prompt adaptation.

## Profiling

Quiet output includes model, effort, permission mode, MCP mode, executor, subagent mode and observed count, class, task type, context budget, prompt template, prompt character counts, usage tokens, cache-read tokens, cache-hit ratio when available, cost, and terminal reason. Note: in quiet JSON mode the internal subagent count may be reported as "unknown" because executor output does not always include tool-use stream events. Prompt reduction is expected to be zero for normal templated prompts because the original request is preserved. Set `CLAUDE_DELEGATE_PROFILE_LOG` to append the same non-secret metadata to JSONL for trend analysis. The bundled `scripts/aggregate-profile-log.py` reads these JSONL records and outputs a concise aggregate summary (plain text by default, `--json` for machine-readable).
