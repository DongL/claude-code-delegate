# ADR 0007: Production Readiness Roadmap

**Status**: Accepted  
**Date**: 2026-05-18  

## Context

Eight production readiness gaps were identified in the claude-code-delegate package:

1. Plaintext Jira credentials in project `.mcp.json`
2. No `pyproject.toml` or installable package metadata
3. No controlled live smoke-test lane for external integrations (Claude, Jira, GitHub)
4. ADR 0005, README, SKILL.md, and `opencode_invoker.py` disagree on `subagent_mode` → `--agent` behavior
5. No cleanup or retention policy for async runtime job files
6. No stable audit artifact contract for delegation attempts, errors, or cost metadata
7. No release readiness checklist or compatibility matrix
8. Provider/MCP/auth errors lack structured, user-facing diagnostics

These gaps are tracked and resolved independently, but they share a common theme: the project is functional and tested, but not yet hardened for production distribution and operation.

## Decision

Treat production readiness as a staged roadmap with eight vertical slices, each independently implementable and verifiable. The following policies apply:

### Deterministic CI Preserved

All existing tests (ADR 0003 baseline: 282 passing, 0 failing) must continue to pass after each slice. No slice may weaken the deterministic test suite.

### Live Smoke Tests Isolated

Any integration test that touches Claude, Jira, or GitHub requires explicit opt-in via `CLAUDE_DELEGATE_SMOKE_TEST=1` env var. These tests never run in default CI.

### Secret-Free Config Required

Project `.mcp.json` must contain zero secrets before the next tagged release. Secrets belong in user-level config (`~/.claude/mcp.json`, env vars, keychain). The project `.mcp.json` may contain only non-secret config (server definitions without credential env vars).

### Docs/Behavior Reconciliation Required

ADR 0005 and any other ADR that disagrees with the implementation must be corrected before the next release. The release readiness checklist must include a docs/behavior audit as a blocking gate.

### Packaging and Release Policy Required

Before the next public release:
- A `pyproject.toml` with version, dependencies, and entry points must exist.
- A release checklist with install verification, compatibility matrix check, and smoke-test pass must be documented and followed.

## Consequences

### Positive

- Production readiness is decomposed into independently grabbable work items, making it easy to parallelize or prioritize.
- The deterministic CI baseline is never weakened.
- Live smoke tests exist but cannot accidentally fire in CI.
- Credentials cannot leak through the project `.mcp.json`.
- Documentation and implementation are reconciled before release.
- Consumers have a reliable install path and version contract.

### Trade-offs

- Live smoke tests require manual or secret-backed setup — they cannot be fully automated in open-source CI without a service account.
- The docs/behavior reconciliation slice may uncover deeper disagreements that require a small code fix or ADR amendment.
- Packaging adds maintenance burden (dependency version bumps, Python version support policy).
- The eight slices may take multiple PRs or releases to complete.

## Cross-References

| Slice | Topic | PRD Section |
|-------|-------|-------------|
| Security/Config | Secret-free MCP config | Security/Config Slice |
| Packaging | pyproject.toml, install verification | Packaging Slice |
| Smoke-Test Lane | Live integration tests | Smoke-Test Lane Slice |
| Docs/Behavior Reconciliation | ADR, README, SKILL, code alignment | Docs/Behavior Reconciliation Slice |
| Runtime Cleanup | Job file retention policy | Runtime Cleanup Slice |
| Observability | Delegation audit artifact contract | Observability Slice |
| Release Readiness | Release checklist, compatibility matrix | Release Readiness Slice |
| Failure Diagnostics | Structured error reporting | Failure Diagnostics Slice |
