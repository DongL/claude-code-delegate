# Claude Code Delegate

## What this is

A toolkit that lets an orchestrating AI (Codex, Cursor, etc.) delegate implementation plans to Claude Code for execution, then review the resulting diff.

When `$claude-code-delegate` is invoked, follow the gate checklist in `SKILL.md` exactly.

## Key files

- `SKILL.md` — The orchestrator contract. This is what Codex/the orchestrator reads to understand the delegation workflow.
- `scripts/run-claude-code.sh` — The wrapper that parses flags and delegates to the pipeline.
- `scripts/pipeline.py` — The delegation pipeline: classify → envelope → invoke → compact → profile.
- `scripts/run-pipeline.py` — Thin CLI entry point that the wrapper calls.
- `scripts/compact_claude_stream.py` — Compacts JSON stream output into a readable report.
- `scripts/aggregate_profile_log.py` — Aggregates CLAUDE_DELEGATE_PROFILE_LOG JSONL into a summary.
- `scripts/jira_safe_text.py` — Strips Markdown for Jira MCP plain-text comments.
- `tests/run_tests.sh` — Test runner (bash, no external deps).
- `CONTEXT.md` — Domain glossary for the project.

## Git workflow

- Never push directly to `main`.
- Create a feature branch for every change: `feat/<short-description>`, `fix/<short-description>`, or `doc/<short-description>`.
- After committing on the branch, push and open a pull request.
- Merge via PR only — even for solo work. This keeps a clean history and gives a checkpoint for review.

## Commands

```bash
# Run tests
bash tests/run_tests.sh

# Test the wrapper directly
bash scripts/run-claude-code.sh --flash "test prompt"
```

## Design notes

- The wrapper defaults to `bypassPermissions` for non-interactive delegation. Use `--interactive` flag (or `CLAUDE_DELEGATE_PERMISSION_MODE=acceptEdits`) for auto-accept edits with tool-command prompts. `--bypass` is kept as an explicit alias for the default.
- Unknown tasks fall back to `deepseek-v4-pro[1m]` and `max` effort. Classified tiny/routine tasks use flash, while debugging and architecture tasks use pro. Override via `--pro`, `--flash`, `--effort`, or the matching env vars.
- MCP defaults to `all`, preserving normal Claude Code project/user MCP discovery. Use `--mcp none` for a strict empty MCP config, or `--mcp jira|linear|sequential-thinking` to load only one server from `.mcp.json`.
- Prompt adaptation defaults to `auto`. Templates preserve the full original prompt; use `--full-context` or `CLAUDE_DELEGATE_CONTEXT_MODE=full` to bypass templates.
- Subagents default to `off`; the wrapper passes `--disallowedTools Task Agent` unless `--allow-subagents` or `CLAUDE_DELEGATE_SUBAGENTS=on` is set.
- Heartbeat runs as a daemon thread in the pipeline. Use `CLAUDE_DELEGATE_HEARTBEAT_SECONDS=0` to disable it.
- Compact output includes profiling metadata. Set `CLAUDE_DELEGATE_PROFILE_LOG` to append JSONL records.
- When consumed by an orchestrator, set `CLAUDE_DELEGATE_DIR` to this project's root before invoking.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **claude-code-delegate** (831 symbols, 1304 relationships, 52 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/claude-code-delegate/context` | Codebase overview, check index freshness |
| `gitnexus://repo/claude-code-delegate/clusters` | All functional areas |
| `gitnexus://repo/claude-code-delegate/processes` | All execution flows |
| `gitnexus://repo/claude-code-delegate/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
