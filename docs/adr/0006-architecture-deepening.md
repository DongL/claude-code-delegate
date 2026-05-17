# ADR 0006: Architecture Deepening — Heartbeat, Pipeline, Classifier, MCP, and Parser Refactors

**Status**: Accepted  
**Date**: 2026-05-17  
**Branch**: `feat/architecture-deepening`

## Context

The codebase had accumulated duplication and mixed responsibilities across several modules:
- Heartbeat monitoring logic duplicated between `invoker.py` and `opencode_invoker.py`
- Pipeline parameter resolution repeated in `run_delegation_pipeline` and `start_delegation_async`
- Envelope/prompt template building scattered between `classifier.py` and a separate `envelope_builder.py`
- MCP server using dynamic `_import_script` instead of direct imports
- Output parser (`compact_claude_stream.py`) handling both Claude Code and OpenCode formats in one monolithic function, with profile logging duplicated in two places

## Decision

Apply five independent refactoring slices, each improving locality (related code together) and leverage (easier to change one thing without affecting others).

### CCDM-36: Extract Shared Heartbeat Monitor

**What**: Created `scripts/heartbeat.py` with `_get_process_cpu_seconds`, `_format_duration`, and `start_heartbeat`. Both `invoker.py` and `opencode_invoker.py` now import from this shared module.

**Why**: CPU tracking, duration formatting, and heartbeat threading were duplicated across two invoker files. Any bug fix or enhancement required changes in both places.

**Improvement**:
- **Locality**: All heartbeat logic lives in one file (140 lines)
- **Leverage**: Adding a new executor only requires importing `start_heartbeat`, not copying 80+ lines

### CCDM-34: Deduplicate Pipeline Parameter Resolution

**What**: Extracted `_resolve_auto`, `_resolve_pipeline_config`, and `_resolve_model` functions in `pipeline.py`. Both `run_delegation_pipeline` and `start_delegation_async` call `_resolve_pipeline_config` for all env-var override logic.

**Why**: The "resolve auto parameters" block (model, effort, permission_mode, mcp_mode, subagents, context) was copy-pasted between sync and async paths. Env var consultation order was implicit and error-prone.

**Improvement**:
- **Locality**: All parameter resolution in 3 functions (~45 lines)
- **Leverage**: New parameters only need one change in `_resolve_pipeline_config`

### CCDM-33: Merge Classifier and Envelope Builder

**What**: Moved `build_prepared_prompt` and `KARPATHY_GUIDELINES` into `classifier.py`. Deleted `envelope_builder.py`. `pipeline.py` imports from `classifier.py` only.

**Why**: Classification and prompt template building are two sides of the same coin — the classification result directly determines which template to apply. Having them in separate files made the flow harder to trace.

**Improvement**:
- **Locality**: Keyword → prepared prompt in one module (182 lines)
- **Leverage**: Adding a new task type requires changes in one file only

### CCDM-32: Slim MCP Server to Declarative Registration

**What**: Replaced `_import_script` with direct module imports at load time (`import aggregate_profile_log as _agg_mod`, `import jira_safe_text as _jira_mod`). Moved `classification_to_dict` to `classifier.py`. MCP tools are one-line registrations.

**Why**: Dynamic script importing made it impossible to statically analyze tool dependencies. The MCP server file was doing too much: tool registration + utility function definitions.

**Improvement**:
- **Locality**: `mcp_server.py` is now 86 lines, purely declarative
- **Leverage**: Adding a tool is one `@server.tool` decorator + one import

### CCDM-35: Split Compact Parser into Per-Backend Adapters

**What**: Created `scripts/claude_adapter.py` (Claude Code stream-json: init/result events) and `scripts/opencode_adapter.py` (OpenCode events: text/step_finish/error). Refactored `parse_compact_output` to detect format and delegate. Removed profile logging from `compact_claude_stream.py` main() — it now happens only in `pipeline.py`.

**Why**: The parser was 296 lines handling two completely different event formats with interleaved logic. Profile logging existed in both `pipeline.py` and `compact_claude_stream.py`, creating potential for inconsistent records.

**Improvement**:
- **Locality**: Each adapter is focused on one format (claude_adapter: 90 lines, opencode_adapter: 100 lines)
- **Leverage**: Adding a new backend means creating one adapter file, not modifying a monolith
- **Consistency**: Profile logging has exactly one call site in `pipeline.py`

## Consequences

### Positive
- Total test count increased from 264 to 278 (14 new adapter unit tests)
- All existing tests pass — zero behavioral changes
- Each module has a single, clear responsibility
- New executor backends can be added by creating one adapter + one invoker import

### Trade-offs
- `parse_compact_output` still exists as a facade for backward compatibility; callers don't need to know about format detection
- Two `_deserialize` functions exist (one per adapter) — identical logic but kept separate to avoid cross-adapter dependency

## Cross-References

| Ticket | Slice | Files Changed |
|--------|-------|---------------|
| CCDM-31 | Parent epic | — |
| CCDM-32 | MCP server slimming | `scripts/mcp_server.py`, `scripts/classifier.py` |
| CCDM-33 | Classifier + envelope merge | `scripts/classifier.py`, `scripts/pipeline.py` |
| CCDM-34 | Pipeline param dedup | `scripts/pipeline.py` |
| CCDM-35 | Parser adapter split | `scripts/claude_adapter.py` (new), `scripts/opencode_adapter.py` (new), `scripts/compact_claude_stream.py` |
| CCDM-36 | Heartbeat extraction | `scripts/heartbeat.py` (new), `scripts/invoker.py`, `scripts/opencode_invoker.py` |
