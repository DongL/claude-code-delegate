# Changelog

## v1.7.0 (2026-05-19)

### Features
- feat: production readiness — pyproject.toml, diagnostics, audit logging, smoke tests, release checklist, ADRs 0006-0007 (#42)
- feat: commit secret-free .mcp.json template, remove from .gitignore

### Documentation
- docs: fix README formatting — line-break OpenCode Zen notes
- docs: note OpenCode Zen has only 1 DeepSeek model (free beta)
- docs: fix Manual install section — add all 3 symlinks and Update subsection

### Bug Fixes
- fix: remove broken --agent flag from opencode invoker (#40)
- fix: revert OpenCode flash mapping to deepseek/deepseek-v4-flash
- fix: map --flash to deepseek-v4-flash-free for Claude Code and OpenCode

### Key Changes
- **Async Delegation Leases**: `--start` / `--poll` with single-flight lease semantics, detached supervisor, and file-based polling. Delegations use atomic claim files preventing duplicate execution; supervisor monitors lease expiry independently of the delegator process.
- **OpenCode Executor**: Second executor backend via `--opencode` removing Anthropic dependency. Routes through DeepSeek V4 Flash on OpenCode Zen (free-tier). Clean executor abstraction separating backend-specific plumbing from delegation logic.
- **CI/CD Quality Gates**: Deterministic no-live-service checks with local/CI parity. `quality-gate.sh` enforces linting, type checking, structural invariants. `release-gate-report.sh` produces pre-release report. GitHub Actions runs gates on every PR and before tagging.
- **Conversational Delegation Guide**: Inline flag usage in natural language with auto-classification. README section shows conversational delegation without memorizing CLI flags.
- **Activity-Aware Heartbeat**: CPU tracking and inactivity timeout with configurable interval. Supervisor detects stalled delegations by monitoring wall-clock activity and CPU utilization, releasing leases for genuinely hung processes.
- **Structured Diagnostics & Audit Logging**: `DelegationError` with typed error codes and resolution hints. Structured JSON audit records capturing every delegation lifecycle event (claim, start, heartbeat, completion, failure).
- **MCP Server**: Four Model Context Protocol tools over stdio JSON-RPC: `delegate_task`, `classify_task`, `aggregate_profile`, `format_jira_text`. Enables IDE integration and multi-agent orchestration through MCP.
- **Secret-Free MCP Config**: Committed `.mcp.json` template with `${ENV_VAR}` expansion — no hardcoded secrets. Drop-in config for new contributors.
- **Packaging**: `pyproject.toml` with setuptools build, `pip install -e .` support, optional MCP extras. PyPI metadata for future distribution.
- **Release Checklist**: `RELEASE.md` with blocking gates, compatibility matrix, smoke test requirements. Documents exact release sequence and tested Python/backend combinations.
