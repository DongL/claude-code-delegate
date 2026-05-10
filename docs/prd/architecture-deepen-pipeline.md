# PRD: Deepen Delegation Pipeline Architecture

## Problem Statement

The claude-code-delegate toolkit has two transports for delegation — the shell wrapper (`run-claude-code.sh`) and the MCP server (`mcp_server.py`). Both implement the same classify → envelope → invoke → compact → profile pipeline, but in different languages and patterns. This duplication causes:

- Bugs fixed in one transport remain in the other
- MCP config extraction is implemented twice (bash+Node.js inline, and Python)
- Profile record construction is copied across two call sites
- `delegation-adapter.py` exists only as a shell bridge, adding serialization overhead

The codebase has four shallow or duplicated modules that should be deepened into a single pipeline with high locality and leverage.

## Solution

Extract a single `run_delegation_pipeline(prompt, config) → DelegationResult` function into a new `scripts/pipeline.py` module. Both transports call this module — the MCP server imports it directly, the bash wrapper calls it via a thin subprocess invocation. Three additional consolidations follow naturally: MCP config extraction moves entirely to Python, profile record construction moves into `profile_logger.py`, and `delegation-adapter.py` is removed as its two jobs are absorbed by the pipeline module.

## User Stories

1. As an orchestrator using the shell wrapper, I want the same delegation behavior as the MCP transport, so that I don't encounter bugs that were already fixed in the other path.
2. As an orchestrator using the MCP server, I want the same delegation behavior as the shell wrapper, so that switching transports doesn't change outcomes.
3. As a maintainer fixing a bug in the delegation pipeline, I want to fix it once, so that I don't need to remember to patch a second implementation in another language.
4. As a developer adding a new task classification rule, I want the new rule to apply identically to both transports, so that classification behavior is consistent.
5. As a developer adding a new MCP mode (e.g., GitHub MCP), I want to add it once in Python, so that both transports pick it up automatically.
6. As a developer changing the profile record schema, I want to change it in one function, so that both the compactor and MCP server produce consistent records.
7. As a new contributor reading the codebase, I want the delegation flow to be traceable in one place, so that I can understand the pipeline without bouncing between bash, Node.js, and Python files.
8. As an operator running the shell wrapper, I want it to stay functional as a fallback (per ADR-0002), so that orchestrators without MCP host support can still delegate.
9. As a reviewer of a PR touching the pipeline, I want tests that cover the pipeline end-to-end in Python, so that I can trust the refactor doesn't regress either transport.

## Implementation Decisions

### New module: pipeline.py

A single `run_delegation_pipeline()` function owns the full orchestration: classify, envelope, resolve config overrides, invoke Claude Code, compact output, log profile record. It imports `classifier`, `envelope_builder`, `invoker`, `compact-claude-stream`, and `profile_logger`. Returns a `DelegationResult` dataclass with result text, usage, cost, classification metadata, and error state.

### Shell wrapper thins to flag parsing + pipeline subprocess

The bash wrapper reduces from ~330 lines to ~150. Flag parsing, validation, and env var defaults stay in bash. After flags are resolved, the wrapper calls `python3 -m scripts.pipeline` as a subprocess with a JSON config on stdin. Exit code forwarding stays. Heartbeat management stays in bash (it needs to run during the subprocess).

### Inline Node.js MCP config extraction deleted

`run-claude-code.sh` lines 250–265 (inline Node.js for extracting a single MCP server from `.mcp.json`) are deleted. `invoker.py:generate_mcp_config` already handles this in Python.

### Profile record construction centralized

`profile_logger.py` gains `build_profile_record(parsed, classification, metadata) → dict`. `compact-claude-stream.py:main()` and `mcp_server.py:delegate_task()` call this instead of building the record dict inline. Field names, default values, and structure live in one place.

### delegation-adapter.py removed

Its two responsibilities — classification and envelope building — move into `pipeline.py`. The adapter's 75 lines of argparse and temp-file serialization are deleted. Tests that exercise the adapter through the bash wrapper are updated to test the pipeline module instead.

### ADR-0002 compliance

The shell wrapper remains the primary transport and fallback. The MCP server remains additive. Both call the same pipeline module. No existing interface is removed — only the internal duplication is eliminated.

### Model/effort/permission resolution

The resolution logic currently split across bash wrapper case statements and MCP server `_resolve_auto` calls is unified in the pipeline module. Explicit flags/env vars override classification defaults following the same precedence in both transports.

## Testing Decisions

- Tests should exercise `run_delegation_pipeline()` with a fake `claude` on PATH, following the same pattern used by the existing test suite (`tests/run_tests.sh` creates `$SANDBOX/claude` as a fake).
- Test the pipeline module directly in Python: given a prompt and config, assert the correct CLI args are passed to `claude`, the output is parsed correctly, and a profile record is written when `CLAUDE_DELEGATE_PROFILE_LOG` is set.
- The existing 159-test suite must continue to pass. Shell wrapper tests that exercise the adapter through bash are updated to test pipeline behavior through the thinner wrapper.
- MCP integration tests continue to test the MCP server's tool contracts; the server's internal call to the pipeline is not mocked.

## Out of Scope

- Changing the classifier's keyword-based rules or adding new task types
- Changing the envelope builder's prompt templates
- Adding a third transport (e.g., REST API)
- Removing the shell wrapper (blocked by ADR-0002)
- Changing the `claude -p` subprocess interface
- Modifying `jira-safe-text.py` or `aggregate-profile-log.py`

## Further Notes

The deepening follows a natural dependency order:

1. Extract `build_profile_record()` into `profile_logger.py` (smallest, no behavioral change)
2. Extract `run_delegation_pipeline()` into `pipeline.py` (core change)
3. Rewire MCP server to call pipeline
4. Rewire bash wrapper to call pipeline, delete inline Node.js
5. Delete `delegation-adapter.py`
6. Update tests

Each step is independently testable and can be a separate issue.
