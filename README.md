# Claude Code Delegate

> Use Codex as the architect, Claude Code as the execution runtime, and DeepSeek V4 as the low-cost model backend.

Claude Code Delegate is a controlled delegation layer for orchestrator-led AI coding workflows. An orchestrator (Codex, Cursor, or another AI) owns planning and review; this toolkit formats the plan, invokes Claude Code as the execution runtime with a DeepSeek V4 backend, compacts the results, and hands them back for orchestrator review. The wrapper does not approve changes — that is the orchestrator's responsibility.

## What This Project Is / Is Not

| This project is... | This project is not... |
|---|---|
| A controlled delegation layer for Codex/Cursor-led workflows | A fully autonomous coding agent |
| A lightweight wrapper that standardizes model, effort, permissions, MCP, and output | "Claude Code connected to DeepSeek" — the model backend is replaceable |
| A toolkit that separates planning (orchestrator) from execution (Claude Code runtime) | A replacement for the orchestrator's planning and review role |
| A compactor that returns concise reports for orchestrator review | An approval system — the wrapper does not accept or reject changes |

## Why Not Use Claude Code with DeepSeek Directly?

You can use Claude Code directly with any provider:

```bash
claude -p "fix the type error in src/cli.py" --model deepseek-v4-flash[1m]
```

Direct invocation works well for single commands, quick checks, and interactive debugging. The wrapper adds value when:

- **Standardized flags**: Model, effort, permission mode, MCP config, and output mode are set consistently across every invocation — no flag drift between tasks.
- **Task classification**: The adapter classifies each prompt (tiny read-only, routine edit, debugging, architecture) and selects appropriate model tier and effort level automatically.
- **Output compaction**: Raw Claude Code JSON stream is compacted into a concise report (changed files, command results, test output, errors) — the orchestrator does not need to parse streaming JSON.
- **Safety defaults**: Subagents are disabled by default to prevent silent recursion. A heartbeat confirms the executor is still running during long tasks.
- **Profile metadata**: Each delegation records model, effort, token usage, and cost for trend analysis.

Use direct `claude -p` when you need a quick answer. Use the wrapper when you want consistent, reviewable delegation with standardized output.

## Overview

Claude Code Delegate is **not** a fully autonomous coding agent. The orchestrator authors the plan and reviews results; the wrapper does not approve changes.

Instead of letting one agent plan, modify files, and approve its own work, this project separates the workflow into two roles:

- **Orchestrator** — Codex, Cursor, or another high-level agent that owns planning and review.
- **Execution runtime** — Claude Code running with DeepSeek V4 as the model backend, focused on implementation.

![Architecture diagram](docs/assets/claude-code-delegate-architecture.svg)

The workflow is:

1. **Plan** — The orchestrator reads project context and produces a concrete implementation plan with ownership boundaries and verification commands.
2. **Delegate** — The adapter classifies the task, selects a prompt envelope, and applies model/effort/permission/output settings. The wrapper invokes Claude Code with consistent flags.
3. **Execute** — Claude Code runs the implementation using the configured model backend (DeepSeek V4 by default). It edits files, runs commands, and generates tests.
4. **Compact** — The wrapper captures Claude Code's JSON output and pipes it through `compact-claude-stream.py`, which returns a concise report: changed files, command output, test results, errors, and execution metadata. The wrapper does **not** approve or reject changes.
5. **Review** — The orchestrator inspects `git diff`, test output, and the compact report, then decides whether to accept, reject, or request a targeted correction pass.
6. **Report** — The final summary from the orchestrator states what changed, which tests ran, and any remaining risks.

You can use this project either as a [Codex skill](#as-a-codex-skill) by symlinking it into your skills directory, or as a [standalone orchestrator](#as-a-standalone-orchestrator) through the bundled wrapper scripts.

## Components

| File | Purpose |
|------|---------|
| `SKILL.md` | Orchestrator contract — defines the delegation loop, resolver, and orchestrator responsibilities |
| `scripts/run-claude-code.sh` | Wrapper — standardizes model, effort, permission mode, MCP config, and output format |
| `scripts/delegation-adapter.py` | Adapter — classifies task size/type, selects prompt template, and sets routing parameters |
| `scripts/compact-claude-stream.py` | Compactor — reduces raw JSON stream to a concise changed-files + test-results report for the orchestrator |
| `scripts/aggregate-profile-log.py` | Profile aggregator — reads CLAUDE_DELEGATE_PROFILE_LOG JSONL and produces summaries |
| `scripts/jira-safe-text.py` | Jira formatter — strips Markdown for plain-text Jira MCP comments |
| `scripts/mcp_server.py` | MCP server — exposes delegation tools (classify, delegate, aggregate, format_jira_text) over stdio JSON-RPC |
| `tests/run_tests.sh` | Test runner — covers wrapper flag parsing, adapter classification, and compactor behavior (not agent correctness) |
| `docs/jira-workflow.md` | Jira-specific delegation conventions |

## Operating Modes

The wrapper supports three permission modes for different trust levels:

| Mode | Flag | Permission Setting | Use Case |
|------|------|-------------------|----------|
| Safe first run | `--interactive` | `acceptEdits` — auto-accepts file edits, prompts on tool commands | First-time use, debugging, or when you want to review commands before they execute |
| Controlled delegation | *(default)* | `bypassPermissions` — fully non-interactive | Normal headless delegation; orchestrator reviews results afterward |
| Automation mode | `--bypass` | `bypassPermissions` — same as default, explicit alias | CI/CD pipelines, trusted repositories, scripts |

> **⚠️ Review caveat**: Permission mode only controls whether Claude Code prompts during execution. The wrapper never approves or rejects changes — that is the orchestrator's responsibility. Always inspect `git diff` and test output before accepting delegated work, regardless of permission mode.

**MCP transport**: `scripts/mcp_server.py` exposes delegation as an MCP server over stdio JSON-RPC. An MCP-compatible host can discover the four tools (`classify_task`, `delegate_task`, `aggregate_profile`, `format_jira_text`) via `tools/list` and invoke them through typed JSON-RPC calls. Requires `pip install mcp`. The shell wrapper remains the primary transport and does not need the `mcp` package — the MCP server is an additive discovery layer for orchestrators that speak MCP.

Example `.mcp.json` snippet (do not create a real file):

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

## Quick Start

```bash
# 1. Clone
git clone https://github.com/DongL/claude-code-delegate.git
cd claude-code-delegate

# 2. Prerequisites: Claude Code installed and python3 available
claude --version
python3 --version

# 3. (Recommended) Symlink into your Codex skill directory
# Preferred (current Codex path)
mkdir -p ~/.agents/skills
ln -sfn "$PWD" ~/.agents/skills/claude-code-delegate

# Legacy Codex path, only if your Codex build still uses it
mkdir -p ~/.codex/skills
ln -sfn "$PWD" ~/.codex/skills/claude-code-delegate

# 4. Run the test suite to verify everything works
bash tests/run_tests.sh

# 5. Try a minimal delegation (safe interactive mode)
./scripts/run-claude-code.sh --interactive --flash "hello from delegate"

# 6. (Optional) For MCP host discovery, add the server to .mcp.json — see
# the MCP transport section in Operating Modes for the config snippet.
```

## Provider Setup

This project defaults to DeepSeek V4 models. Before running the wrapper, configure Claude Code to use DeepSeek as the model backend. Two options:

### Option A: Environment variables (recommended)

Set these in your shell profile (`.zshrc`, `.bashrc`) or before each session:

```bash
export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
export ANTHROPIC_AUTH_TOKEN=<your DeepSeek API key>
export ANTHROPIC_MODEL=deepseek-v4-pro[1m]
export ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-pro[1m]
export ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-pro[1m]
export ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-flash[1m]
export CLAUDE_CODE_SUBAGENT_MODEL=deepseek-v4-flash[1m]
export CLAUDE_CODE_EFFORT_LEVEL=max
```

Get your API key at [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys).

Verify it works:

```bash
claude -p "hello" --model deepseek-v4-flash[1m]
```

### Option B: cc-switch (GUI)

[cc-switch](https://github.com/farion1231/cc-switch) is a cross-platform desktop app that manages provider configuration across Claude Code, Codex, and other AI tools. It ships with 50+ provider presets including DeepSeek — no manual env vars needed. Install it, select DeepSeek from the provider list, and click to activate.

> **Caveat**: Model names and provider URLs vary by Claude Code provider adapter or proxy — cc-switch, OpenRouter, custom endpoints, and other adapters may use different identifiers. If `claude -p "hello" --model deepseek-v4-flash[1m]` fails, debug your provider configuration before assuming the wrapper is the problem. The wrapper passes the model name through unchanged; it does not translate or remap model identifiers.

---

## Real-World Demos

```bash
# Fix a README typo
./scripts/run-claude-code.sh --interactive "fix the typo 'Recieve' to 'Receive' in README.md"

# Add a unit test for an existing function
./scripts/run-claude-code.sh --interactive "add a unit test for the parse_args() function in src/cli.py"

# Review a PR diff and suggest improvements
./scripts/run-claude-code.sh --interactive "review git diff HEAD~1 and report issues"
```

## Usage Modes

### As a Codex skill

Symlink the project into a Codex skill directory so Codex discovers `SKILL.md` and can invoke the delegation loop:

```bash
# Preferred (current Codex path)
mkdir -p ~/.agents/skills
ln -sfn "$PWD" ~/.agents/skills/claude-code-delegate

# Legacy Codex path, only if your Codex build still uses it
mkdir -p ~/.codex/skills
ln -sfn "$PWD" ~/.codex/skills/claude-code-delegate
```

The resolver in `SKILL.md` finds the wrapper script in any of these locations:

1. `$CLAUDE_DELEGATE_DIR` (explicit override — set this to use a non-default install path)
2. `$HOME/.agents/skills/claude-code-delegate` (current Codex path)
3. `$HOME/.codex/skills/claude-code-delegate` (legacy Codex path)

No shell-profile setup required — the resolver makes first-run work without env vars.

### As a standalone orchestrator

Any AI or human can act as the orchestrator by reading `SKILL.md` and invoking the wrapper directly:

```bash
./scripts/run-claude-code.sh --interactive "implement this feature"
```

Or with an explicit project root (useful when running from a different working directory):

```bash
CLAUDE_DELEGATE_DIR=/path/to/claude-code-delegate \
  ./scripts/run-claude-code.sh --interactive "implement this feature"
```

The orchestrator is responsible for the loop: plan, delegate, review, correct, report. `SKILL.md` serves as the contract defining each step.

## CLI Usage

```bash
# Safe first run — auto-accepts file edits, prompts on tool commands (recommended)
./scripts/run-claude-code.sh --interactive "your prompt here"

# Default (pro model, quiet output, non-interactive bypass)
./scripts/run-claude-code.sh "your prompt here"

# Flash model
./scripts/run-claude-code.sh --flash "your prompt here"

# Override classified effort for one invocation
./scripts/run-claude-code.sh --effort max "your prompt here"

# Stream output (for debugging)
./scripts/run-claude-code.sh --stream "your prompt here"

# Automation mode — fully non-interactive, no permission prompts (CI / trusted repos)
./scripts/run-claude-code.sh --bypass "your prompt here"

# Disable project/user MCP servers for implementation-only tasks
./scripts/run-claude-code.sh --mcp none "your prompt here"

# Load only Jira MCP from .mcp.json
./scripts/run-claude-code.sh --mcp jira "update the issue status"

# Disable prompt adaptation while debugging
./scripts/run-claude-code.sh --full-context "your prompt here"

# Allow Claude Code to spawn its own subagents for this invocation
./scripts/run-claude-code.sh --allow-subagents "your prompt here"

# Environment variable overrides
CLAUDE_DELEGATE_MODEL='deepseek-v4-flash[1m]' \
CLAUDE_DELEGATE_EFFORT=medium \
CLAUDE_DELEGATE_PERMISSION_MODE=bypassPermissions \
CLAUDE_DELEGATE_MCP_MODE=none \
CLAUDE_DELEGATE_CONTEXT_MODE=full \
CLAUDE_DELEGATE_SUBAGENTS=on \
CLAUDE_DELEGATE_HEARTBEAT_SECONDS=15 \
CLAUDE_DELEGATE_PROFILE_LOG=logs/delegation-profile.jsonl \
  ./scripts/run-claude-code.sh "your prompt here"
```

See [SECURITY.md](SECURITY.md) for a detailed breakdown of permission modes, risks, and trust tiers.

When consumed by an orchestrator, `SKILL.md` provides a `resolve_delegator` helper that finds the wrapper script across multiple install paths. See `SKILL.md` for the full resolver definition.

MCP mode defaults to `all`, which preserves Claude Code's normal MCP discovery. `--mcp none` uses a strict empty MCP config, while `--mcp jira`, `--mcp linear`, and `--mcp sequential-thinking` load only that server from `.mcp.json` or `CLAUDE_DELEGATE_MCP_CONFIG_PATH`.

The wrapper classifies tasks before invocation. Tiny read-only checks use flash/low effort/minimal context, routine edits and Jira operations use flash/medium effort, debugging uses pro/high effort, architecture work uses pro/max effort, and unknown prompts fall back to the original full prompt with pro/max. Known task templates preserve the full original request; the wrapper does not truncate executor context to save Claude Code-side tokens. Compact output shows the selected class, task type, context budget, prompt template, token usage, cost, and optional JSONL profiling metadata.

Subagents are disabled by default via `--disallowedTools Task Agent` so a delegated executor does not silently spawn another local agent while quiet mode buffers output. Quiet mode writes a heartbeat to stderr immediately and every 30 seconds; set `CLAUDE_DELEGATE_HEARTBEAT_SECONDS=0` to disable it.

## Profiling Analysis

Set `CLAUDE_DELEGATE_PROFILE_LOG` to append profiling metadata to a JSONL file after each delegation. Each record contains model, effort, task type, token usage, cache hit data, cost, and prompt character counts. The bundled `scripts/aggregate-profile-log.py` reads these logs and produces a concise aggregate summary:

```bash
# Enable profiling
export CLAUDE_DELEGATE_PROFILE_LOG=logs/delegation-profile.jsonl
./scripts/run-claude-code.sh --flash "your prompt here"

# Aggregate analysis (plain text, default)
python3 scripts/aggregate-profile-log.py "$CLAUDE_DELEGATE_PROFILE_LOG"

# Machine-readable JSON output
python3 scripts/aggregate-profile-log.py --json "$CLAUDE_DELEGATE_PROFILE_LOG"

# Or pass the path directly
python3 scripts/aggregate-profile-log.py logs/delegation-profile.jsonl
```

## Requirements

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview) installed and configured
- Access to a Claude Code-compatible model
- `python3` available for the JSON compactor

## License

MIT
