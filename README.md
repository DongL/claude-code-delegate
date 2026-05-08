# Claude Code Delegate

Delegate implementation plans from an orchestrator (Codex, Cursor, or another AI) to Claude Code for execution, then review the resulting diff — all in a plan-execute-review loop.

## Overview

This skill/toolkit lets an orchestrator own the planning and review phases while Claude Code handles implementation. Use it as a [Codex skill](#as-a-codex-skill) (symlink into `~/.codex/skills/`) or as a [standalone orchestrator](#as-a-standalone-orchestrator) via the bundled wrapper. The workflow is:

1. **Plan** — Orchestrator reads context and produces a concrete plan.
2. **Execute** — Orchestrator invokes Claude Code via the bundled wrapper to execute the plan.
3. **Review** — Orchestrator inspects the diff and test results.
4. **Correct** (optional) — One targeted correction pass if needed.
5. **Report** — Final summary with changed files, tests, and residual risk.

## Components

| File | Purpose |
|------|---------|
| `SKILL.md` | Skill definition — the contract that drives orchestrator behavior |
| `scripts/run-claude-code.sh` | Wrapper that invokes Claude Code with consistent flags |
| `scripts/compact-claude-stream.py` | Compacts JSON stream output into a readable final report |
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
ln -sf "$PWD" ~/.codex/skills/claude-code-delegate

# 4. Run the test suite to verify everything works
bash tests/run_tests.sh

# 5. Try a minimal delegation
./scripts/run-claude-code.sh --flash "hello from delegator"
```

## Usage Modes

### As a Codex skill

Symlink the project into a Codex skill directory so Codex discovers `SKILL.md` and can invoke the delegation loop:

```bash
# Current Codex skill path (preferred)
ln -sf "$CLAUDE_DELEGATOR_DIR" ~/.agents/skills/claude-code-delegate

# Legacy Codex skill path
ln -sf "$CLAUDE_DELEGATOR_DIR" ~/.codex/skills/claude-code-delegate
```

Then use `/claude-code-delegate` in Codex to trigger the plan-execute-review workflow. Codex reads `SKILL.md` which includes a resolver that finds the wrapper script in any of these locations:

1. `$CLAUDE_DELEGATOR_DIR` (explicit override)
2. `$HOME/.agents/skills/claude-code-delegate` (current Codex path)
3. `$HOME/.codex/skills/claude-code-delegate` (legacy Codex path)

No shell-profile setup required — the resolver makes first-run work without env vars.

### As a standalone orchestrator

Any AI or human can act as the orchestrator by reading `SKILL.md` and invoking the wrapper directly:

```bash
./scripts/run-claude-code.sh --flash "implement this feature"
```

Or with an explicit project root (useful when running from a different working directory):

```bash
CLAUDE_DELEGATOR_DIR=/path/to/claude-code-delegate \
  ./scripts/run-claude-code.sh --flash "implement this feature"
```

The orchestrator is responsible for the loop: plan, delegate, review, correct, report. `SKILL.md` serves as the contract defining each step.

## CLI Usage

```bash
# Default (pro model, quiet output)
./scripts/run-claude-code.sh "your prompt here"

# Flash model
./scripts/run-claude-code.sh --flash "your prompt here"

# Stream output (for debugging)
./scripts/run-claude-code.sh --stream "your prompt here"

# Environment variable overrides
CLAUDE_DELEGATOR_MODEL='deepseek-v4-flash[1m]' \
CLAUDE_DELEGATOR_EFFORT=medium \
CLAUDE_DELEGATOR_PERMISSION_MODE=bypassPermissions \
  ./scripts/run-claude-code.sh "your prompt here"
```

When consumed by an orchestrator, SKILL.md provides a `resolve_delegator` helper that finds the wrapper script across multiple install paths. See `SKILL.md` for the full resolver definition.

## Requirements

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview) installed and configured
- Access to a Claude Code-compatible model
- `python3` available for the JSON compactor

## License

MIT
