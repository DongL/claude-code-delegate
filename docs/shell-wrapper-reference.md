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
| *(none)* | `CLAUDE_DELEGATE_THINKING_TOKENS` | Explicit thinking token budget (unset by default) |
| *(none)* | `CLAUDE_DELEGATE_HEARTBEAT_SECONDS` | Heartbeat interval in seconds (default `30`, `0` disables) |
| *(none)* | `CLAUDE_DELEGATE_PROFILE_LOG` | JSONL path for profiling metadata |
| *(none)* | `CLAUDE_DELEGATE_DIR` | Install path override for resolver |
| *(none)* | `CLAUDE_DELEGATE_MCP_CONFIG_PATH` | Path to `.mcp.json` for single-server MCP mode |

## Delegation Suitability

Do not delegate tiny local inspection tasks unless the user explicitly asks to use Claude Code. If the task is read-only, deterministic, local to the current machine, and likely needs three or fewer shell commands, the orchestrator should run it directly and report the result. Delegation has leverage for implementation, multi-file edits, independent execution, Jira/MCP work, or tasks where Claude Code is specifically requested.

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

Default output mode is `quiet`: the pipeline asks Claude Code for final JSON output, parses it internally via `compact-claude-stream.py`, and returns only the final result plus model, permission mode, usage, cost, and terminal status. This is the preferred mode for normal delegation because the orchestrator does not need to ingest every thinking or partial-message event.

Use `--stream` only when debugging Claude Code itself, diagnosing permission hangs, inspecting tool events, or preserving the raw stream is necessary:

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

Default delegation disables Claude Code's built-in `Task`/`Agent` subagent tool. This keeps the executor from spawning another local agent that can run for a long time while quiet mode buffers all output. Allow subagents only when the plan explicitly needs Claude Code to parallelize inside its own process:

```bash
"$(resolve_delegator)" --allow-subagents "$PROMPT"
```

Quiet mode prints progress to stderr immediately and every 30 seconds while Claude Code is still running. Set `CLAUDE_DELEGATE_HEARTBEAT_SECONDS=0` to disable the heartbeat or another integer to change the interval.

## MCP Mode

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

Supported modes are `all`, `none`, `jira`, `linear`, and `sequential-thinking`. `none` uses Claude Code's `--strict-mcp-config --mcp-config` with an empty MCP config. Specific server modes use `--strict-mcp-config --mcp-config` with a generated one-server config read from `.mcp.json`, or from `CLAUDE_DELEGATE_MCP_CONFIG_PATH` when set.

Built-in Claude Code file and shell tools are not MCP servers, so `--mcp none` still allows normal implementation work. It only suppresses project/user MCP server loading.

Environment variable override:

```bash
CLAUDE_DELEGATE_MCP_MODE=jira \
  "$(resolve_delegator)" "$PROMPT"
```

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

For known task types, the wrapper wraps the full original prompt in a task-specific envelope before calling Claude Code. Current templates cover:

- `read_only_scan`
- `code_edit`
- `jira_operation`
- `architecture_review`

Each template preserves the full original request, task goal, allowed scope, constraints, and verification expectations. Unknown task types fall back to the original prompt. Use `--full-context` or `CLAUDE_DELEGATE_CONTEXT_MODE=full` when debugging prompt adaptation.

## Profiling

Quiet output includes model, effort, permission mode, MCP mode, class, task type, context budget, prompt template, prompt character counts, usage tokens, cache-read tokens, cache-hit ratio when available, cost, and terminal reason. Prompt reduction is expected to be zero for normal templated prompts because the original request is preserved. Set `CLAUDE_DELEGATE_PROFILE_LOG` to append the same non-secret metadata to JSONL for trend analysis. The bundled `scripts/aggregate-profile-log.py` reads these JSONL records and outputs a concise aggregate summary (plain text by default, `--json` for machine-readable).
