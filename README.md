# Claude Code Delegate

> Use Codex as the architect, Claude Code as the executor, and DeepSeek V4 as the low-cost coding engine.

Delegate implementation plans from an orchestrator (Codex, Cursor, or another AI) to Claude Code for execution, then review the resulting diff — all in a plan-execute-review loop.

## Overview

Claude Code Delegate is a lightweight delegation toolkit for AI coding workflows.

Instead of letting one agent plan, modify files, and approve its own work, this project separates the workflow into two roles:

- **Orchestrator** — Codex, Cursor, or another high-level agent that owns planning and review.
- **Execution engine** — Claude Code running with DeepSeek V4 as the model backend, focused on implementation.

```text
┌──────────────────────┐
│ Orchestrator         │
│ Codex / Cursor / You │
│                      │
│ - Understand task    │
│ - Create plan        │
│ - Review results     │
└──────────┬───────────┘
           │
           │ concrete plan
           ▼
┌──────────────────────┐
│ Claude Code Delegate │
│ Skill + Wrapper      │
│                      │
│ - Resolve paths      │
│ - Select model       │
│ - Build prompt       │
│ - Control execution  │
└──────────┬───────────┘
           │
           │ adapted execution prompt
           ▼
┌──────────────────────────────┐
│ Claude Code + DeepSeek V4    │
│ Execution Engine             │
│                              │
│ - Edit files                 │
│ - Run commands               │
│ - Generate tests             │
│ - Fix implementation issues  │
└──────────┬───────────────────┘
           │
           │ diff + logs + test results
           ▼
┌──────────────────────┐
│ Verification Output  │
│                      │
│ - Code diff          │
│ - Test results       │
│ - Execution summary  │
│ - Errors / warnings  │
└──────────┬───────────┘
           │
           │ evidence for review
           ▼
┌──────────────────────┐
│ Orchestrator Review  │
│                      │
│ - Accept patch       │
│ - Request correction │
│ - Reject unsafe diff │
└──────────────────────┘
```

The workflow is:

1. **Plan** — The orchestrator reads the project context and produces a concrete implementation plan.
2. **Delegate** — The wrapper converts that plan into a Claude Code execution prompt and applies model, effort, permission, and output settings.
3. **Execute** — Claude Code runs the implementation using DeepSeek V4 as the model backend.
4. **Verify** — The wrapper returns changed files, command output, test results, and execution metadata.
5. **Review** — The orchestrator inspects the diff and decides whether to accept, reject, or request a targeted correction pass.
6. **Report** — The final response summarizes what changed, which tests ran, and any remaining risks.

You can use this project either as a [Codex skill](#as-a-codex-skill) by symlinking it into your skills directory, or as a [standalone orchestrator](#as-a-standalone-orchestrator) through the bundled wrapper scripts.

## Components

| File | Purpose |
|------|---------|
| `SKILL.md` | Skill definition — the contract that drives orchestrator behavior |
| `scripts/run-claude-code.sh` | Wrapper that invokes Claude Code with consistent flags |
| `scripts/delegation-adapter.py` | Classifies tasks, wraps full prompts in task templates, and emits profiling metadata |
| `scripts/compact-claude-stream.py` | Compacts JSON stream output into a readable final report |
| `scripts/aggregate-profile-log.py` | Aggregates CLAUDE_DELEGATOR_PROFILE_LOG JSONL into a summary |
| `scripts/jira-safe-text.py` | Strips Markdown for Jira MCP plain-text comments |
| `tests/run_tests.sh` | Test runner |
| `docs/jira-workflow.md` | Jira-specific delegation conventions |

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
./scripts/run-claude-code.sh --interactive --flash "hello from delegator"
```

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
ln -sfn "$CLAUDE_DELEGATE_DIR" ~/.agents/skills/claude-code-delegate

# Legacy Codex path, only if your Codex build still uses it
mkdir -p ~/.codex/skills
ln -sfn "$CLAUDE_DELEGATE_DIR" ~/.codex/skills/claude-code-delegate
```

Then use `/claude-code-delegate` in Codex to trigger the plan-execute-review workflow. Codex reads `SKILL.md` which includes a resolver that finds the wrapper script in any of these locations:

1. `$CLAUDE_DELEGATE_DIR` (explicit override)
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
CLAUDE_DELEGATOR_MODEL='deepseek-v4-flash[1m]' \
CLAUDE_DELEGATOR_EFFORT=medium \
CLAUDE_DELEGATOR_PERMISSION_MODE=bypassPermissions \
CLAUDE_DELEGATOR_MCP_MODE=none \
CLAUDE_DELEGATOR_CONTEXT_MODE=full \
CLAUDE_DELEGATOR_SUBAGENTS=on \
CLAUDE_DELEGATOR_HEARTBEAT_SECONDS=15 \
CLAUDE_DELEGATOR_PROFILE_LOG=logs/delegation-profile.jsonl \
  ./scripts/run-claude-code.sh "your prompt here"
```

See [SECURITY.md](SECURITY.md) for a detailed breakdown of permission modes, risks, and trust tiers.

When consumed by an orchestrator, SKILL.md provides a `resolve_delegator` helper that finds the wrapper script across multiple install paths. See `SKILL.md` for the full resolver definition.

MCP mode defaults to `all`, which preserves Claude Code's normal MCP discovery. `--mcp none` uses a strict empty MCP config, while `--mcp jira`, `--mcp linear`, and `--mcp sequential-thinking` load only that server from `.mcp.json` or `CLAUDE_DELEGATOR_MCP_CONFIG_PATH`.

The wrapper classifies tasks before invocation. Tiny read-only checks use flash/low effort/minimal context, routine edits and Jira operations use flash/medium effort, debugging uses pro/high effort, architecture work uses pro/max effort, and unknown prompts fall back to the original full prompt with pro/max. Known task templates preserve the full original request; the wrapper does not truncate executor context to save Claude Code-side tokens. Compact output shows the selected class, task type, context budget, prompt template, token usage, cost, and optional JSONL profiling metadata.

Subagents are disabled by default via `--disallowedTools Task Agent` so a delegated executor does not silently spawn another local agent while quiet mode buffers output. Quiet mode writes a heartbeat to stderr immediately and every 30 seconds; set `CLAUDE_DELEGATOR_HEARTBEAT_SECONDS=0` to disable it.

## Profiling Analysis

Set `CLAUDE_DELEGATOR_PROFILE_LOG` to append profiling metadata to a JSONL file after each delegation. Each record contains model, effort, task type, token usage, cache hit data, cost, and prompt character counts. The bundled `scripts/aggregate-profile-log.py` reads these logs and produces a concise aggregate summary:

```bash
# Enable profiling
export CLAUDE_DELEGATOR_PROFILE_LOG=logs/delegation-profile.jsonl
./scripts/run-claude-code.sh --flash "your prompt here"

# Aggregate analysis (plain text, default)
python3 scripts/aggregate-profile-log.py "$CLAUDE_DELEGATOR_PROFILE_LOG"

# Machine-readable JSON output
python3 scripts/aggregate-profile-log.py --json "$CLAUDE_DELEGATOR_PROFILE_LOG"

# Or pass the path directly
python3 scripts/aggregate-profile-log.py logs/delegation-profile.jsonl
```

## Requirements

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview) installed and configured
- Access to a Claude Code-compatible model
- `python3` available for the JSON compactor

## License

MIT
