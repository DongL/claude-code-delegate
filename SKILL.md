---
name: claude-code-delegate
description: Delegate an orchestrator-authored implementation plan to Claude Code, then review the resulting diff. Use when the user wants an orchestrator (e.g., Codex) to plan while Claude Code executes, or wants a plan-execute-review loop.
---

# Claude Code Delegate

## Contract

Use this workflow when the user wants an orchestrator to own planning/review while Claude Code performs implementation. Each delegation pass must clear every mandatory gate. If a gate does not apply, note the skip and move to the next.

### Mandatory Gates

#### Plan Gate
- [ ] Read enough local context to understand the affected area.
- [ ] Show a concrete implementation plan to the user BEFORE invoking the wrapper. This is a hard gate: do not batch the wrapper invocation in the same tool call as the plan. The user must be able to read and object before execution starts. Include ownership boundaries and verification commands.
- [ ] Present the plan as a normal assistant message in the conversation. Do not satisfy this gate by printing the plan through a shell command, tool output, log line, or hidden artifact.
- [ ] Confirm the plan does not broaden scope beyond what was asked. Scope creep is the most common violation — plan only what the user requested.

#### Delegate Gate
- [ ] Show the exact orchestrator-authored prompt to the user BEFORE invocation. This is a hard gate: the user must see what will be sent to Claude Code before execution starts. Present the prompt as a normal assistant message — not through a shell command, tool output, or hidden artifact.
- [ ] If the prompt contains secrets, private user data, or excessive copied context, show a redacted version and state what was redacted. Never redact material scope, ownership boundaries, prohibited actions, or verification commands.
- [ ] Invoke only through `run-claude-code.sh` via the resolver function.
- [ ] Default to quiet/compact mode (`--quiet`). This preserves orchestrator tokens and produces a compact final report. Streaming output is noisy, wastes context window, and should only be used for wrapper/API/permission diagnosis. Before re-streaming, check stderr heartbeat — if alive, executor is running; no need to restart.
- [ ] The pipeline auto-classifies model tier and effort from the prompt. If the orchestrator knows the task is simpler or harder than keyword matching suggests, override with `--pro` / `--flash` / `--effort`. Prefer explicit overrides for non-trivial tasks.
- [ ] Default `--mcp all` for general tasks. Use `--mcp jira` when the executor needs Jira MCP tools (issue queries, transitions, comments). Use `--mcp none` for isolated execution without MCP servers.
- [ ] Include prompt requirements per the Prompt Requirements section.

#### Execute Gate
- [ ] Do not make local implementation edits while Claude Code is executing.
- [ ] If Claude Code appears stuck, re-run with `--stream` to diagnose — do not take over locally.
- [ ] If Claude Code produces a wrong or incomplete result, stop and re-delegate the correction — do not patch locally.

#### Async Delegation Gate (Lease + Single-Flight)

The `--start` / `--poll` modes enforce single-flight lease semantics to prevent duplicate delegations.

- [ ] A running delegation job owns an execution lease. Do not start a second delegation while one is running.
- [ ] Use `--start` to launch in background; use `--poll <job_id>` to check status.
- [ ] Do not treat a long-running invocation as evidence of stuckness by itself. Poll the heartbeat/log-tail first.
- [ ] If `--start` returns `"status": "lease_held"`, the orchestrator must wait for that job to complete. No retry, reduced correction plan, takeover, or second delegation is allowed while the lease is active.

#### Compact Gate
- [ ] Wait for the wrapper to complete.
- [ ] Show the compact result: changed files, verification results, token usage/cost, terminal status.
- [ ] **STOP.** The next two gates (Review, Report) are mandatory and must not be skipped even for read-only tasks. For read-only tasks where `git diff --stat` is empty, note that explicitly.

#### Review Gate
- [ ] Show Claude Code's output to the user before giving the orchestrator's review.
- [ ] Run `git diff --stat` and inspect relevant diffs locally.
- [ ] Run focused tests or verification commands.
- [ ] Do not accept unreviewed changes just because Claude Code completed successfully.

#### Correction Gate
- [ ] If the diff is wrong or incomplete, show a targeted correction plan to the user.
- [ ] Re-delegate the correction through Claude Code using the same wrapper invocation.
- [ ] Show the correction pass output before the next iteration or final review.
- [ ] Surface results after each correction pass so the user can intervene if convergence stalls.

#### Report Gate
- [ ] Final summary includes: changed files, tests run, residual risk, and any caveats.

### Local Implementation Ban

While this skill is active, the orchestrator may inspect, plan, and review locally but must not make implementation edits locally. Every code change must flow through Claude Code via the wrapper. The orchestrator may only edit locally if the user explicitly authorizes a Codex takeover.

## Invocation

Two transports are available: the shell wrapper (this section) and the MCP server (see [MCP Transport](#mcp-transport) below). Both use the same classifier, envelope builder, invoker, and compactor.

Always invoke Claude Code through the bundled wrapper. The orchestrator resolves the script path using this fallback chain — no mandatory setup step required:

```bash
resolve_delegator() {
  for dir in \
    "${CLAUDE_DELEGATE_DIR:-}" \
    "$HOME/.agents/skills/claude-code-delegate" \
    "$HOME/.codex/skills/claude-code-delegate"
  do
    if [ -n "$dir" ] && [ -x "$dir/scripts/run-claude-code.sh" ]; then
      echo "$dir/scripts/run-claude-code.sh"
      return 0
    fi
  done
  echo "claude-code-delegate not found. Set CLAUDE_DELEGATE_DIR or install the skill." >&2
  return 1
}
```

Then delegate via:

```bash
"$(resolve_delegator)" "$PROMPT"
```

| Flag | Env Var | Effect |
|------|---------|--------|
| `--start` | — | Launch in background, return job_id JSON (async mode). |
| `--poll JOB_ID` | — | Poll async job status. |
| `--pro` / `--flash` | `CLAUDE_DELEGATE_MODEL` | Model selection |
| `--effort VALUE` | `CLAUDE_DELEGATE_EFFORT` | Reasoning budget |
| `--quiet` / `--stream` | `CLAUDE_DELEGATE_OUTPUT_MODE` | Output format |
| `--bypass` / `--interactive` | `CLAUDE_DELEGATE_PERMISSION_MODE` | Permission handling |
| `--mcp MODE` | `CLAUDE_DELEGATE_MCP_MODE` | MCP server loading |
| `--full-context` | `CLAUDE_DELEGATE_CONTEXT_MODE` | Prompt adaptation |
| `--allow-subagents` | `CLAUDE_DELEGATE_SUBAGENTS` | Subagent control |

For the full CLI reference including all flags, env vars, and modes, see [Shell Wrapper CLI Reference](docs/shell-wrapper-reference.md).

## MCP Transport

The bundled `scripts/mcp_server.py` exposes delegation as MCP tools over stdio JSON-RPC transport, providing an alternative to the shell wrapper. Both transports use `scripts/pipeline.py` — a single delegation pipeline (classify → envelope → invoke → compact → profile) — as their shared implementation. The MCP server imports it directly; the shell wrapper calls it via `scripts/run-pipeline.py`.

### Adding to .mcp.json

```json
{
  "mcpServers": {
    "claude-code-delegate": {
      "command": "python3",
      "args": ["scripts/mcp_server.py"]
    }
  }
}
```

Add this to your project `.mcp.json` (or the orchestrator's `.mcp.json`) and the MCP host will discover and invoke delegation tools automatically.

### Available Tools

| Tool | Purpose |
|------|---------|
| `classify_task` | Classify a prompt by size, type, model tier, effort, permission mode, and context budget |
| `delegate_task` | Full delegation pipeline: classify, envelope, invoke, compact, return structured result with usage and cost |
| `aggregate_profile` | Aggregate `CLAUDE_DELEGATE_PROFILE_LOG` JSONL into a text or JSON summary |
| `format_jira_text` | Strip Markdown formatting for Jira-safe plain text |

### MCP vs Shell Wrapper

| Axis | Shell Wrapper | MCP Transport |
|------|---------------|---------------|
| Discovery | Orchestrator must know the resolver path | MCP client discovers tools via `tools/list` |
| Contract | CLI flags and exit codes | Typed JSON-RPC request/response with structured errors |
| Errors | Exit code + stderr | JSON-RPC error objects with standard codes |
| Invocation | `"$(resolve_delegator)" "$PROMPT"` | `tools/call` with typed arguments |
| Dependencies | bash + python3 | Requires `pip install mcp` |

The shell wrapper remains the primary transport and does not require the `mcp` package. The MCP server is additive — when an MCP host is available, it provides typed discovery and structured responses without changing the shell-wrapper interface.

## Prompt Requirements

The prompt sent to Claude Code must include:

- [ ] The user's goal.
- [ ] The concrete plan to execute.
- [ ] Ownership boundaries: files/modules it may touch.
- [ ] A warning not to revert unrelated user changes.
- [ ] A recommendation to apply Karpathy-style coding guidelines if available. Key principles: surgical changes, prefer boring code, avoid overcomplication, surface assumptions, define verifiable success criteria.
- [ ] Verification commands to run.
- [ ] A request to report changed files and command results.

Invoke the wrapper directly without adding `timeout`. If Claude Code appears silent, re-run with `--stream` and inspect the wrapper's stream-json events before assuming it is stuck. For long-running tasks, prefer `--start` / `--poll` — the lease prevents duplicate delegations and the orchestrator can poll for progress without assuming the executor is stuck.

After Claude Code returns, show the user Claude Code's output. In quiet mode, show the compact final report. In stream mode, prefer the final result block when it is concise; if the stream output is noisy, summarize the key lines but preserve changed files, command results, errors, and any stated caveats.

## Issue Tracker Integration

When delegating Jira or issue tracker work, apply Jira-safe plain text formatting (no Markdown). See [docs/jira-workflow.md](docs/jira-workflow.md) for details and the `scripts/jira-safe-text.py` utility.

## Known Failure Modes

- **Apparent hang**: `claude -p` with default permissions blocks on permission prompts. The wrapper defaults to `bypassPermissions` to avoid this. Use `--interactive` (acceptEdits) to observe tool commands before they run.
- **Silent executor**: During long delegations, the pipeline prints a heartbeat to stderr every 30s. If Claude Code appears silent, check stderr first — an active heartbeat means it's running. Set `CLAUDE_DELEGATE_HEARTBEAT_SECONDS=0` to disable (e.g., CI).
- **Premature kill/retry**: The orchestrator may assume Claude Code is stuck and start a reduced correction plan. `--start` / `--poll` prevents this via single-flight lease. Poll with `--poll <job_id>` rather than restarting.
- **Provider/auth errors**: Usually means the provider can't serve the model, or the token is expired. Confirm `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, and model values without printing secrets.
