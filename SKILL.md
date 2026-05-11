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
- [ ] Show a concrete implementation plan to the user, including ownership boundaries and verification commands.
- [ ] Confirm the plan does not broaden scope beyond what was asked.

#### Delegate Gate
- [ ] Invoke only through `run-claude-code.sh` via the resolver function.
- [ ] Default to quiet/compact mode (`--quiet`). Use `--stream` only for wrapper/API/permission diagnosis. Before re-streaming, check stderr heartbeat — if alive, executor is running; no need to restart.
- [ ] Include prompt requirements per the Prompt Requirements section.

#### Execute Gate
- [ ] Do not make local implementation edits while Claude Code is executing.
- [ ] If Claude Code appears stuck, re-run with `--stream` to diagnose — do not take over locally.
- [ ] If Claude Code produces a wrong or incomplete result, stop and re-delegate the correction — do not patch locally.

#### Compact Gate
- [ ] Wait for the wrapper to complete.
- [ ] Show the compact result: changed files, verification results, token usage/cost, terminal status.

#### Review Gate
- [ ] Run `git diff --stat` and inspect relevant diffs locally.
- [ ] Run focused tests or verification commands.
- [ ] Do not accept unreviewed changes.

#### Correction Gate
- [ ] If the diff is wrong or incomplete, show a targeted correction plan to the user.
- [ ] Re-delegate the correction through Claude Code using the same wrapper invocation.
- [ ] Surface results after each correction pass so the user can intervene if convergence stalls.

#### Report Gate
- [ ] Final summary includes: changed files, tests run, residual risk, and any caveats.

### Local Implementation Ban

While this skill is active, the orchestrator may inspect, plan, and review locally but must not make implementation edits locally. Every code change must flow through Claude Code via the wrapper. The orchestrator may only edit locally if the user explicitly authorizes a Codex takeover.

### Quiet/Compact Default

Always prefer `--quiet` mode. This preserves orchestrator tokens and produces a compact final report. Streaming output is noisy, wastes context window, and should only be used for wrapper/API/permission diagnosis.

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

## Common Violations

- **Noisy stream watching.** Using `--stream` as the default output mode wastes orchestrator tokens. Reserve streaming for diagnosis.
- **Local patching during delegation.** Editing files locally while Claude Code is running or after it produces a suboptimal result. Stop and re-delegate instead.
- **Skipping compact output.** Not waiting for the wrapper to complete or not showing the compact result to the user.
- **Accepting without review.** Trusting Claude Code output without running `git diff --stat`, inspecting diffs, or running focused checks.
- **Scope creep.** Broadening the plan beyond what the user asked without re-confirming.

## Known Failure Mode

Plain `claude -p` with default permissions can appear to hang because Claude Code is waiting on permission requests. The wrapper default `bypassPermissions` avoids this entirely by suppressing all permission prompts. For debugging sessions where you want to observe tool commands before they run, use the `--interactive` flag (which sets `acceptEdits` — auto-accepts file edits but prompts on Bash/tool commands).

During long-running delegations, the pipeline prints a heartbeat to stderr every 30 seconds (`Claude Code still running: model=... effort=...`). If Claude Code appears silent, check stderr first — an active heartbeat means the executor is running, its absence means it has stopped or crashed. Set `CLAUDE_DELEGATE_HEARTBEAT_SECONDS=0` to disable the heartbeat (e.g. for CI pipelines).

Provider or org/auth access errors usually mean Claude Code is not currently switched to a provider that can serve `deepseek-v4-pro[1m]`, or the provider token in `~/.claude/settings.json` is malformed/expired. Confirm the configured `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, and model values without printing secret token contents.
