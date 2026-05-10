# PRD: Claude Code Delegate as MCP Server

## Problem Statement

Today, orchestrators (Codex, Cursor, custom agents) invoke claude-code-delegate through a shell script wrapper (`run-claude-code.sh`). This has three friction points:

1. **Discovery dependency**: The orchestrator must locate the wrapper script via the `resolve_delegator` resolver chain. If the skill isn't symlinked into the right directory, delegation silently fails.

2. **Shell invocation overhead**: Every delegation spawns a bash process that spawns a Python adapter that spawns Claude Code. The orchestrator has no programmatic visibility into task classification, progress, or intermediate state — only the final compacted report.

3. **No structured integration**: The wrapper's interface is CLI flags + environment variables. There's no way to list available operations, validate parameters upfront, or get typed responses. Every orchestrator must re-implement the same flag-parsing and output-parsing logic.

An MCP server solves all three: discovery is automatic via MCP's server registration, invocation is a JSON-RPC tool call with structured inputs/outputs, and the tool schema serves as self-documenting API contract.

## Solution

Package claude-code-delegate as an MCP server that exposes its core capabilities — task delegation, classification, profile aggregation, and Jira formatting — as MCP tools. The MCP server reuses all existing deep modules (classifier, envelope builder, compactor, profile aggregator, Jira formatter) unchanged. The shell wrapper remains functional for backward compatibility; the MCP server is additive.

Orchestrators add the server to their `.mcp.json` or Claude Code MCP config, then invoke tools directly:

```json
{
  "mcpServers": {
    "claude-code-delegate": {
      "command": "python3",
      "args": ["path/to/mcp_server.py"]
    }
  }
}
```

## User Stories

1. As an orchestrator agent, I want to delegate an implementation task via a single MCP tool call, so that I don't need to locate and invoke a shell script.
2. As an orchestrator agent, I want the delegation result returned as structured JSON (status, changed files, test output, token usage, cost), so that I can programmatically decide whether to accept or request corrections.
3. As an orchestrator agent, I want to classify a task without executing it, so that I can preview which model and effort level will be used before committing to the delegation.
4. As an orchestrator agent, I want to stream delegation progress events during long-running tasks, so that I can show the user real-time status instead of a silent wait.
5. As an orchestrator agent, I want to aggregate delegation profile logs into a summary, so that I can analyze cost and token trends across multiple delegations.
6. As an orchestrator agent, I want to convert Markdown to Jira-safe plain text via a tool call, so that I can format issue comments without invoking a separate script.
7. As a developer setting up the MCP server, I want it to auto-discover from `.mcp.json` like any other MCP server, so that I don't need custom resolver logic.
8. As a developer debugging a delegation, I want to run the MCP server in a mode that preserves backward compatibility with the existing shell wrapper, so that I can fall back to the CLI when needed.
9. As a developer running the test suite, I want MCP server integration tests that validate tool contracts without requiring a live Claude Code invocation, so that CI stays fast.
10. As an orchestrator agent, I want the MCP server to respect all existing env var overrides (model, effort, permission mode, MCP mode, heartbeat, profile log), so that my existing configuration continues to work.
11. As an orchestrator agent, I want the delegation tool to accept the same parameters as the shell wrapper (model tier, effort, permission mode, MCP mode, context mode, subagent toggle), so that I can translate existing delegations to MCP tool calls without learning a new interface.
12. As an operator, I want the MCP server to fail gracefully with a structured error when Claude Code is not installed or the provider is misconfigured, so that I get actionable diagnostics instead of a raw shell exit code.

## Implementation Decisions

### Modules

**MCP Server Core** — New module. Entry point using the Python MCP SDK (`mcp` package). Handles stdio JSON-RPC transport, tool registration, and server lifecycle. Thin layer that delegates to existing modules.

**Claude Code Invoker** — New module. Extracts subprocess invocation logic from `run-claude-code.sh` (lines 223-305). Takes a typed config dict (model, effort, permission_mode, mcp_mode, subagent_mode, prompt) and returns a subprocess result. Handles MCP config file generation (currently inline Node.js in the bash wrapper, lines 250-267). Handles heartbeat via a background thread.

**MCP Tools Registry** — New module. Defines tool input schemas (JSON Schema) and maps tool names to handler functions. The tool schemas are the API contract.

**Task Classifier** — Extracted from existing `delegation-adapter.py`. Pure function, no changes to logic. The `classify_prompt()` function and `Classification` dataclass become a standalone module importable by both the MCP server and the existing adapter script.

**Prompt Envelope Builder** — Extracted from existing `delegation-adapter.py`. Pure function, no changes to logic. The `build_prepared_prompt()` function becomes a standalone module.

**Output Compactor** — Existing `compact-claude-stream.py`. Interface unchanged (stdin JSON → stdout report). Imported by the MCP server for in-process use.

**Profile Logger** — Logic extracted from `compact-claude-stream.py` lines 148-173 (JSONL append). Standalone module with `append_profile_record()` and the existing `aggregate_profile_log.py` aggregator.

**Jira Formatter** — Existing `jira-safe-text.py`. Interface unchanged. Imported by the MCP server.

### Tool Schemas

```
delegate_task:
  prompt: string (required)
  model_tier: "pro" | "flash" | "auto" (default "auto")
  effort: "low" | "medium" | "high" | "max" | "auto" (default "auto")
  permission_mode: "bypassPermissions" | "acceptEdits" | "auto" (default "auto")
  mcp_mode: "all" | "none" | "jira" | "linear" | "sequential-thinking" (default "all")
  context_mode: "auto" | "full" (default "auto")
  allow_subagents: boolean (default false)
  output_mode: "quiet" | "stream" (default "quiet")
  → { classification, result, usage, cost, terminal_reason }

classify_task:
  prompt: string (required)
  → { class, task_type, model, effort, permission_mode, context_budget }

aggregate_profile:
  profile_log_path: string (required)
  format: "text" | "json" (default "text")
  → { summary } | { json_record }

format_jira_text:
  markdown: string (required)
  → { plain_text }
```

### Architecture Decision: Python MCP SDK

The server uses the `mcp` Python package (stdio transport) rather than implementing JSON-RPC from scratch. The MCP SDK handles connection lifecycle, capability negotiation, and tool schema validation. This keeps the server core thin and avoids reinventing protocol machinery.

### Architecture Decision: Additive, Not Rewrite

The shell wrapper, adapter, compactor, and all existing scripts remain functional and unchanged. The MCP server imports their logic as Python modules. The `delegation-adapter.py` is refactored into a callable module (classifier + envelope builder) that both the adapter CLI and the MCP server import. This preserves backward compatibility while enabling the new transport.

### Architecture Decision: Subprocess Invocation

The MCP server invokes `claude -p` as a subprocess, same as the bash wrapper. It does not embed Claude Code or call it through an internal API. This keeps the invocation path identical to the shell wrapper, avoiding divergence in behavior.

### Architecture Decision: Heartbeat via Background Thread

When output mode is `quiet`, the invoker spawns a daemon thread that writes progress messages to stderr at the configured interval (default 30s, 0 disables). This replaces the bash wrapper's background subshell heartbeat (lines 186-197).

## Testing Decisions

### What makes a good test

Tests verify external behavior (tool contracts, exit codes, output shape), not implementation details. Integration tests use a fake `claude` on PATH (same pattern as the existing test suite). No real Claude Code invocation in CI.

### Modules tested

- **MCP Tools Registry**: Schema validation, parameter defaults, error paths
- **Claude Code Invoker**: Subprocess invocation with all flag combinations (mirrors the existing bash wrapper tests)
- **Task Classifier**: Same classification tests as existing adapter tests
- **MCP Server Core**: Tool dispatch, error handling, lifecycle

### Prior art

The existing `tests/run_tests.sh` uses a fake `claude` script that records invocation args and returns valid JSON. The MCP integration tests extend this pattern: a test harness starts the MCP server, sends JSON-RPC requests over stdin, and asserts on responses.

## Out of Scope

- **Streaming transport (HTTP/SSE)**: Initial release uses stdio only. HTTP transport can be added later without changing tool implementations.
- **Authentication/authorization**: The MCP server inherits the local machine's trust boundary. No auth layer.
- **Remote delegation**: The server runs on the same machine as Claude Code. Remote execution is out of scope.
- **Batched/parallel delegation**: One `delegate_task` call = one Claude Code invocation. No queuing, pooling, or concurrent execution.
- **Result persistence**: Delegation results are returned inline. No database, no history beyond the optional profile JSONL.
- **Web UI or dashboard**: The server is an MCP backend, not a web application.

## Further Notes

- The MCP server name registered during initialization is `claude-code-delegate`.
- All existing environment variables (`CLAUDE_DELEGATE_MODEL`, `CLAUDE_DELEGATE_EFFORT`, etc.) are read by the server at tool invocation time, not at server startup, so configuration changes take effect without restart.
- The server logs to stderr (MCP stdio convention). Tool results go to stdout as JSON-RPC responses.
- Python 3.10+ required (matches the existing `from __future__ import annotations` usage).
