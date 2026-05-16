# Claude Code Delegate Glossary

## Orchestrator

The entity that owns the planning and review phases of the delegation workflow. May be an AI (Codex, Claude Code, Cursor, etc.) or a human. The orchestrator produces a plan, invokes Claude Code for execution, then inspects the results.

Not to be confused with "Executor" (Claude Code), which only implements and verifies.

## Executor

Claude Code, acting on a concrete plan supplied by the Orchestrator. The Executor does not design — it reads context, implements, runs verification commands, and reports results.

## Delegation

The act of the Orchestrator handing a bounded implementation task to the Executor, with explicit ownership boundaries and verification criteria.

## Provider Model

The model name passed to Claude Code (e.g., `deepseek-v4-pro[1m]`). This is not a standard Anthropic model ID — it reflects a custom provider (DeepSeek V4 via [`cc-switch`](https://github.com/farion1231/cc-switch)) that the target Claude Code installation is configured to use. The Orchestrator knows what model its Claude Code instance can serve. The wrapper defaults to `deepseek-v4-pro[1m]` but is overridable via `CLAUDE_DELEGATE_MODEL`.

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

The `resolve_delegator` function in SKILL.md that locates the wrapper script at runtime. It checks three locations in order: `CLAUDE_DELEGATE_DIR` (explicit override), `~/.agents/skills/claude-code-delegate` (current Codex path), and `~/.codex/skills/claude-code-delegate` (legacy). This avoids requiring environment variable setup for first-time Codex users.

## MCP Server

The `scripts/mcp_server.py` entry point that exposes `classify_task`, `delegate_task`, `aggregate_profile`, and `format_jira_text` as MCP tools over stdio JSON-RPC transport. Allows an MCP-compatible orchestrator to discover and invoke delegation operations through typed contracts rather than shell invocation. Requires `pip install mcp`.

## MCP Tool

A typed JSON-RPC operation registered by the MCP server. Each tool has a name, description, and typed input schema (`inputSchema`). The four bundled tools are `classify_task` (prompt classification), `delegate_task` (full delegation pipeline with classify → envelope → invoke → compact), `aggregate_profile` (profile log analysis from CLAUDE_DELEGATE_PROFILE_LOG JSONL), and `format_jira_text` (Markdown-to-plain-text conversion via `jira-safe-text.py`).

## MCP Transport

The stdio JSON-RPC protocol used by `scripts/mcp_server.py` to communicate with MCP hosts. Each message is a single newline-delimited JSON line (`\n`-separated JSON-RPC). Distinct from the shell-wrapper transport (`scripts/run-claude-code.sh`) which uses CLI flags, exit codes, and stdout/stderr. The MCP transport provides typed contracts and structured errors; the shell wrapper provides universal fallback without Python package dependencies beyond the standard library.

## Executor Backend

The coding agent that performs implementation work. Two backends are supported:

| Backend | Command | Permission Flag | Notes |
|---------|---------|----------------|-------|
| `claude-code` (default) | `claude -p` | `--permission-mode` | Original executor, supports effort/reasoning budget |
| `opencode` | `opencode run` | `--dangerously-skip-permissions` | Open source alternative, uses Zen or BYO providers |

Selected via `--executor` flag or `CLAUDE_DELEGATE_EXECUTOR` env var. Both backends share the same pipeline (classify → envelope → invoke → compact → profile). OpenCode does not support the `--effort` parameter — reasoning budget is configured via the model provider instead.
