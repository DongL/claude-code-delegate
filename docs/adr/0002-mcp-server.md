# Turn claude-code-delegate into an MCP server

The claude-code-delegate skill currently exposes its capabilities through a shell-script wrapper (`scripts/run-claude-code.sh`). This requires orchestrators to locate the script at runtime via a resolver chain, invoke it as a subprocess, and parse compacted text output. An MCP server replaces this with standard JSON-RPC tool calls — automatic discovery, typed inputs/outputs, and no shell invocation overhead.

## Status

Proposed

## Why this matters

The shell-wrapper approach has three structural problems that an MCP server eliminates:

### 1. Discovery fragility

Orchestrators must locate the wrapper script via the `resolve_delegator` chain (check `CLAUDE_DELEGATE_DIR`, then `~/.agents/skills/`, then `~/.codex/skills/`). If the skill isn't symlinked into one of these paths, delegation silently fails. An MCP server registers with the MCP host — the orchestrator calls `tools/list` and discovers capabilities without filesystem inspection.

### 2. Shell invocation tax

Every delegation spawns: bash wrapper → Python adapter → `claude -p` subprocess → Python compactor. Each layer adds latency and a potential failure point. The orchestrator gets only the final compacted report — no visibility into task classification, progress, or intermediate state. An MCP server collapses this into a single tool call with structured progress events.

### 3. No programmatic contract

The wrapper's interface is CLI flags + environment variables. Orchestrators must re-implement flag parsing and output parsing. There's no way to list available operations, validate parameters upfront, or get typed responses. MCP tool schemas serve as self-documenting API contracts — parameters are validated by the MCP host before the tool executes.

### Concrete evidence from today's session

During this ADR's drafting session, we encountered three wrapper-class issues that an MCP server would prevent:

- **Misclassification**: "create a new project on jira and move all the issues" was classified as `code_edit` instead of `jira_operation` because the classifier checked `edit_words` before `jira`. An MCP `classify_task` tool would let the orchestrator preview and override the classification before execution.
- **Silent hangs**: Two delegations hung for 10-16 minutes on Jira project creation, which the MCP server doesn't support. An MCP server would return a structured error in seconds rather than waiting on a subprocess timeout.
- **Credential discovery**: `--mcp all` mode failed to discover the user's Jira MCP config in `~/.claude/mcp.json` on 3 of 4 attempts. Explicit `--mcp jira` required creating a project `.mcp.json` with credentials. An MCP server shares the host's MCP transport — no separate credential discovery needed.

## Considered Options

- **Stay with shell wrapper only** — simpler to maintain, no new dependencies. Rejected: the resolver chain, shell invocation overhead, and lack of typed contracts are inherent to the shell approach and cannot be fixed incrementally.
- **Add a REST API alongside the wrapper** — would solve the typed contract problem but adds HTTP server complexity (auth, port management, CORS). Rejected: MCP solves the same problem with stdio transport (no network surface) and automatic host integration.
- **Rewrite as MCP server, drop the wrapper** — cleanest but breaks backward compatibility for orchestrators that invoke the shell wrapper directly. Rejected: the wrapper must remain functional as a fallback.
- **Add MCP server, keep the wrapper (additive)** — both interfaces coexist. The MCP server imports existing Python modules (classifier, envelope builder, compactor, invoker, profile logger, Jira formatter) unchanged. The wrapper stays as the CLI fallback. **Accepted.**

## Architecture

The MCP server is a thin stdio JSON-RPC layer over the existing deep modules:

```
Orchestrator (Codex / Cursor / Claude Code)
       │
       │ MCP JSON-RPC (stdio)
       ▼
┌──────────────────────┐
│  mcp_server.py       │  ← new entry point (mcp SDK)
│  Tools:              │
│  - delegate_task     │
│  - classify_task     │
│  - aggregate_profile │
│  - format_jira_text  │
└──────┬───────────────┘
       │ imports
       ▼
┌──────────────────────┐
│  Existing modules    │
│  - classifier.py     │  ← extracted from delegation-adapter
│  - envelope_builder  │  ← extracted from delegation-adapter
│  - invoker.py        │  ← extracted from run-claude-code.sh
│  - compactor.py      │  ← existing compact-claude-stream
│  - profile_logger    │  ← extracted from compact-claude-stream
│  - jira-safe-text    │  ← existing, unchanged
└──────────────────────┘
```

The shell wrapper continues to work as before. The MCP server is additive — no existing interface is removed.

## Risk: MCP SDK dependency

The server depends on the `mcp` Python package. This is a young SDK with potential API churn. Mitigation: the server core is ~50 lines of glue code. If the SDK changes, the migration cost is low. The wrapper remains available as a fallback during any SDK migration.

## Risk: Two interfaces, one codebase

Maintaining both the shell wrapper and the MCP server risks divergence — a bug fixed in one path may persist in the other. Mitigation: both paths share the same Python modules for classification, envelope building, invocation, compaction, profiling, and Jira formatting. The only duplicated logic is the CLI flag parsing in the bash wrapper and the MCP tool parameter schemas — these are thin layers over the shared modules.

## Consequences

- Orchestrators gain automatic discovery, typed tool contracts, and structured error handling without filesystem resolver chains or shell invocation overhead.
- The `mcp` Python package becomes a new dependency. Python 3.10+ required (already the case for `from __future__ import annotations`).
- `SKILL.md` must document both the MCP transport and the shell resolver as fallback.
- All existing scripts remain functional and tested — the MCP server is additive.
- The test suite extends with MCP integration tests (start server, send JSON-RPC over stdin, assert responses) using the same fake-claude pattern as existing tests.
