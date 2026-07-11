# Claude Code Delegate Glossary

## Orchestrator

The entity that owns the planning and review phases of the delegation workflow. May be an AI (Codex, Claude Code, Cursor, etc.) or a human. The orchestrator produces a plan, invokes the selected executor backend for execution, then inspects the results.

Not to be confused with "Executor" (Claude Code or OpenCode), which only implements and verifies.

## Executor

Claude Code or OpenCode, acting on a concrete plan supplied by the Orchestrator. The Executor does not design — it reads context, implements, runs verification commands, and reports results.

Common pairings:

| Orchestrator | Executor | How |
|--------------|----------|-----|
| Codex | Claude Code | Default `claude-code` backend |
| Claude Code | OpenCode | `--opencode`, `--executor opencode`, or MCP `executor="opencode"` |
| Any MCP/shell-capable host | Claude Code or OpenCode | Same pipeline, selected per invocation |

## Delegation

The act of the Orchestrator handing a bounded implementation task to the Executor, with explicit ownership boundaries and verification criteria.

## Provider Model

The model name passed to the selected executor (e.g., `deepseek-v4-pro[1m]` for Claude Code or `opencode/deepseek-v4-flash-free` for OpenCode). Claude Code model IDs may reflect a custom provider (DeepSeek V4 via [`cc-switch`](https://github.com/farion1231/cc-switch)) rather than a standard Anthropic model. OpenCode model IDs usually use provider-prefixed names. The orchestrator knows what model its selected executor can serve. The wrapper defaults to `deepseek-v4-pro[1m]` but is overridable via `CLAUDE_DELEGATE_MODEL`.

## Pro vs Flash

The two capability tiers of the DeepSeek V4 model family:

| Axis | Pro | Flash |
|------|-----|-------|
| Params | 1.6T total / 49B active | 284B total / 13B active |
| Purpose | Hard reasoning, architecture, debugging | Fast, cheap, routine coding |
| Context | 1M tokens | 1M tokens |
| Thinking | Supported | Supported |
| Cost | Higher | Lower |

The `[1m]` suffix is a routing label for 1M-token context, not a capability tier. Thinking budget (`--effort`) is orthogonal to model tier — `effort=max` on Flash is not the same as Pro.

## Correction Iteration

The practice of repeating correction passes until the diff is correct, rather than limiting to a fixed number of attempts. Each pass is surfaced to the user so they can intervene if convergence stalls.

## Script Resolver

The `resolve_delegator` function in SKILL.md that locates the wrapper script at runtime. It checks three locations in order: `CLAUDE_DELEGATE_DIR` (explicit override), `~/.agents/skills/claude-code-delegate` (current agent skill path), and `~/.codex/skills/claude-code-delegate` (legacy Codex path). This avoids requiring environment variable setup for first-time users.

## MCP Server

The `scripts/mcp_server.py` entry point that exposes delegation, polling, classification, profile aggregation, and Jira text formatting as MCP tools over stdio JSON-RPC transport. Allows an MCP-compatible orchestrator to discover and invoke delegation operations through typed contracts rather than shell invocation. Requires `pip install mcp`.

## MCP Tool

A typed JSON-RPC operation registered by the MCP server. Each tool has a name, description, and typed input schema (`inputSchema`). The bundled tools are `classify_task` (prompt classification), `delegate_task` (full delegation pipeline with classify → envelope → invoke → compact), `start_delegation` (async launch), `poll_delegation` (full async poll), `poll_delegation_compact` (lightweight async poll), `aggregate_profile` (profile log analysis from CLAUDE_DELEGATE_PROFILE_LOG JSONL), `format_jira_text` (Markdown-to-plain-text conversion via `jira-safe-text.py`), and the change-contract tools `create_change_spec`, `get_change_spec`, `delegate_change_task`, `record_change_task_review` (see [Change Contract](#change-contract) below).

## Change Contract

A persisted JSON file (`change.json` under `.claude-delegate/changes/<change-id>/` in the target project) that lets an orchestrator write a plan once — goal, non-goals, requirements, tasks, dependencies, ownership boundaries, verification commands — and reference it by ID across multiple sessions or delegation passes, instead of re-explaining the plan in every prompt. Each delegation of a task appends an append-only run record under `runs/run-NNNN.json`.

The delegate only *transports and executes* tasks from the contract via `--change`/`--task` (shell) or `delegate_change_task` (MCP) — it never marks a task `verified` on its own. A task's status moves `pending → delegated` automatically; only the orchestrator, after independently checking the diff and tests, can move it to `verified` (or `failed`/`blocked`) via `scripts/change-spec.py review` or the `record_change_task_review` MCP tool. A task is only ready for delegation when the contract validates, the change is `active`, the task is `pending`/`failed`, and every dependency is `verified` (not `delegated`). Change/task/requirement IDs must be lowercase — an uppercase-hyphenated ID like `TASK-001` collides with the classifier's ticket-detection pattern and gets misrouted.

## MCP Transport

The stdio JSON-RPC protocol used by `scripts/mcp_server.py` to communicate with MCP hosts. Each message is a single newline-delimited JSON line (`\n`-separated JSON-RPC). Distinct from the shell-wrapper transport (`scripts/run-claude-code.sh`) which uses CLI flags, exit codes, and stdout/stderr. The MCP transport provides typed contracts and structured errors; the shell wrapper provides universal fallback without Python package dependencies beyond the standard library.

## Executor Backend

The coding agent that performs implementation work. Two backends are supported:

| Backend | Command | Permission Flag | Notes |
|---------|---------|----------------|-------|
| `claude-code` (default) | `claude -p` | `--permission-mode` | Original executor, supports effort/reasoning budget |
| `opencode` | `opencode run` | `--dangerously-skip-permissions` | Open source alternative, uses Zen or BYO providers |

Selected via `--executor` flag or `CLAUDE_DELEGATE_EXECUTOR` env var. Both backends share the same pipeline (classify → envelope → invoke → compact → profile). OpenCode does not support the `--effort` parameter — reasoning budget is configured via the model provider instead.
