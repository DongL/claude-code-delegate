# Claude Code Delegate

> Let your AI orchestrator (Codex, Cursor, Claude Code) delegate implementation tasks to Claude Code — with DeepSeek V4 as the low-cost model backend.

An orchestrator owns planning and review. This toolkit handles everything in between: classify the task, wrap it in a prompt template, invoke Claude Code, compact the output, and return a structured result. Neither the wrapper nor the pipeline approves changes — that's the orchestrator's job.

## What This Is / Is Not

| This project is... | This project is not... |
|---|---|
| A delegation layer for AI-to-AI coding workflows | A fully autonomous coding agent |
| A pipeline that standardizes classification, invocation, and output compaction | A replacement for the orchestrator's planning and review role |
| Transport-agnostic: MCP server + shell wrapper, same pipeline | "Claude Code connected to DeepSeek" — the model backend is replaceable |

## How Your Orchestrator Calls It

### MCP transport (preferred)

Add to your project's `.mcp.json`:

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

Your orchestrator discovers four tools via `tools/list` and delegates with one typed call:

```
delegate_task(prompt="fix the type error in src/cli.py")
// → { classification, result, usage, cost_usd, terminal_reason }
```

Also available: `classify_task`, `aggregate_profile`, `format_jira_text`. Requires `pip install mcp`.

### Shell wrapper (fallback)

Same pipeline, invoked through a CLI:

```bash
./scripts/run-claude-code.sh "fix the type error in src/cli.py"
```

The wrapper parses flags, calls `scripts/run-pipeline.py`, and prints a compact report. No `mcp` package needed. Full CLI reference in [docs/shell-wrapper-reference.md](docs/shell-wrapper-reference.md).

Both transports share `scripts/pipeline.py` — the same classify → envelope → invoke → compact → profile logic.

## The Delegation Loop

1. **Plan** — The orchestrator reads project context and produces a concrete plan with ownership boundaries and verification commands.
2. **Delegate** — The pipeline classifies the task, wraps it in a prompt template, resolves model/effort/permission settings, invokes Claude Code, and compacts the output.
3. **Execute** — Claude Code implements the plan using the configured model backend (DeepSeek V4 by default).
4. **Compact** — The pipeline parses Claude Code's JSON output into a concise report: result text, token usage, cost, and terminal status.
5. **Review** — The orchestrator inspects `git diff`, test output, and the compact report, then decides to accept, reject, or request a correction pass.
6. **Report** — The orchestrator gives a final summary: what changed, which tests ran, residual risk.

Correction iterations repeat steps 2–5 until the diff is correct.

## Why Not `claude -p` Directly?

```bash
claude -p "fix the type error" --model deepseek-v4-flash[1m]
```

Direct invocation works for single commands. The delegation layer adds value when:

- **Task classification** — automatically selects model tier and effort based on prompt content (flash for edits, pro for debugging/architecture).
- **Prompt templates** — wraps the orchestrator's plan in a task envelope with coding guidelines and ownership boundaries.
- **Output compaction** — raw JSON stream becomes a structured report the orchestrator can parse programmatically.
- **Safety defaults** — subagents disabled, heartbeat confirms the executor is still alive, profile metadata recorded.
- **Consistent invocation** — model, effort, permissions, MCP config identical across every delegation.

Use `claude -p` for quick answers. Use the delegation layer when you want consistent, reviewable, AI-to-AI execution.

## Installation

### One-command

```bash
curl -fsSL https://raw.githubusercontent.com/DongL/claude-code-delegate/main/install.sh | bash
```

### Manual

```bash
git clone https://github.com/DongL/claude-code-delegate.git ~/.claude-code-delegate
mkdir -p ~/.agents/skills
ln -sfn ~/.claude-code-delegate ~/.agents/skills/claude-code-delegate
bash ~/.claude-code-delegate/tests/run_tests.sh
pip3 install mcp  # optional, for MCP server
```

### As a Codex skill

Symlink into the skill directory so Codex discovers `SKILL.md`:

```bash
mkdir -p ~/.agents/skills
ln -sfn "$PWD" ~/.agents/skills/claude-code-delegate
```

The resolver in `SKILL.md` finds the wrapper across these paths:

1. `$CLAUDE_DELEGATE_DIR` — explicit override
2. `$HOME/.agents/skills/claude-code-delegate` — current Codex path
3. `$HOME/.codex/skills/claude-code-delegate` — legacy Codex path

## Provider Setup

This project defaults to DeepSeek V4 models via environment variables:

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

Get your API key at [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys). Verify:

```bash
claude -p "hello" --model deepseek-v4-flash[1m]
```

Or use [cc-switch](https://github.com/farion1231/cc-switch) for GUI-based provider management with 50+ presets.

Override the model for a single delegation:

```bash
CLAUDE_DELEGATE_MODEL=claude-sonnet-4-6 ./scripts/run-claude-code.sh "your prompt"
```

## CLI Reference

| Flag | Effect |
|------|--------|
| *(none)* | Pro model, quiet output, bypass permissions (default) |
| `--pro` / `--flash` | Model tier selection |
| `--effort low\|medium\|high\|max` | Reasoning budget override |
| `--interactive` | Auto-accept edits, prompt on tool commands (safe first run) |
| `--bypass` | Fully non-interactive (explicit alias for default) |
| `--stream` | Raw stream-json output (for debugging) |
| `--mcp all\|none\|jira\|linear\|sequential-thinking` | MCP server loading |
| `--full-context` | Skip prompt template wrapping |
| `--allow-subagents` | Allow Claude Code to spawn subagents |

Env var equivalents and full details: [docs/shell-wrapper-reference.md](docs/shell-wrapper-reference.md). Permission modes and security: [SECURITY.md](SECURITY.md).

## Components

| File | Purpose |
|------|---------|
| `SKILL.md` | Orchestrator contract — delegation loop, resolver, responsibilities |
| `scripts/pipeline.py` | Delegation pipeline — shared by both transports |
| `scripts/run-pipeline.py` | CLI entry point for shell wrapper consumers |
| `scripts/run-claude-code.sh` | Shell wrapper — flag parsing only |
| `scripts/mcp_server.py` | MCP server — typed JSON-RPC tools over stdio |
| `scripts/compact-claude-stream.py` | Output parser — JSON stream → structured report |
| `scripts/profile_logger.py` | Profile record construction and JSONL append |
| `scripts/aggregate-profile-log.py` | Profile log aggregation and summarization |
| `scripts/jira-safe-text.py` | Markdown → Jira-safe plain text converter |
| `tests/run_tests.sh` | Test runner — pipeline, invocation, and compaction |
| `docs/shell-wrapper-reference.md` | Full CLI flag/env-var reference |
| `docs/jira-workflow.md` | Jira-specific delegation conventions |

## Profiling

Set `CLAUDE_DELEGATE_PROFILE_LOG` when delegating to record each invocation:

```
delegate_task(prompt="fix the typo")
// profiling appends to CLAUDE_DELEGATE_PROFILE_LOG automatically
```

Then read the aggregate via MCP:

```
aggregate_profile(profile_log_path="logs/profile.jsonl", format="text")
// → "Records: 12  Success: 10  Error: 2 ..."
```

Shell fallback for the same operations:

```bash
export CLAUDE_DELEGATE_PROFILE_LOG=logs/profile.jsonl
./scripts/run-claude-code.sh "your prompt"
python3 scripts/aggregate-profile-log.py logs/profile.jsonl
```

Each record: model, effort, task type, token usage, cache hit ratio, cost, prompt character counts.

## Requirements

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview)
- `python3` (standard library only; `pip install mcp` optional for MCP server)
- Access to a Claude Code-compatible model

## License

MIT
