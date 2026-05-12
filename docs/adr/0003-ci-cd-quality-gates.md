# Adopt CI/CD quality gates as the merge/release confidence boundary

The claude-code-delegate project has a shell test suite (`bash tests/run_tests.sh`) that passes locally but no automated CI enforcement. Without formalized CI/CD quality gates, every merge relies on manual discipline — the author remembering to run tests, check isolation assumptions, and validate that the delegation pipeline works across environments. This ADR establishes CI/CD quality gates as the merge/release confidence boundary: automated, deterministic checks that run on every PR and main-branch push.

## Status

Accepted (2026-05-12)

## Considered Options

- **No CI gates (status quo)** — cheapest to maintain but no enforcement. Rejected: manual discipline does not scale across contributors or time.
- **CI gates with real external services** — full integration tests against live Claude Code, Jira, and GitHub. Rejected: requires secrets, tokens, and live-service availability; fragile and expensive for ordinary PR checks.
- **CI gates with mocked/sandboxed external services** — deterministic, fast, no secrets required. The test suite already follows this pattern with fake `claude` and mock MCP. Extending it to CI is incremental. **Accepted.**

## Decision

Adopt CI/CD quality gates as the merge/release confidence boundary:

1. **Default CI gate is deterministic and no-live-service.** All checks that run on PR and main-branch push use fake `claude`, mock MCP servers, and no external tokens. This makes CI fast, reproducible, and free of flaky external dependencies.

2. **External systems are out of default CI.** Real Claude provider invocation, Jira transitions, and GitHub release publishing are handled by mocks in CI, with explicit smoke tests or manual/escalated gates reserved for controlled secret-backed environments.

3. **Local and CI parity.** A single documented command mirrors CI gate behavior locally. Running the same command that CI runs gives the same result — no divergence between developer machine and CI environment.

4. **Isolated Claude runtime supports determinism.** The recent isolated Claude runtime work (commit `06122f6`) reduces coupling to personal `~/.claude` configuration and sandbox plugins, making CI behavior more predictable across machines.

5. **Failed gate blocks merge and release documentation.** A red gate means the change must not merge. Release documentation records gate status, commit/tag, tests run, and residual risk.

## Risk: External-system regressions not caught by default CI

The default CI gate mocks external systems (Claude provider, Jira, GitHub). Regressions in real external-system integration — MCP transport changes, Jira API drift, provider authentication issues — will not be caught by the default gate.

**Mitigation:**
- Document external-system caveats clearly in README/SKILL and the quality gate policy. (Implemented in `README.md` Quality Gates section.)
- Reserve smoke tests against live external systems for manual pre-release checks or a future secret-backed CI environment.
- Treat external-system gate failures as blocking for releases but not for ordinary PRs.

**External-system gate strategy (decided):**
- Default CI (.github/workflows/quality-gate.yml) uses deterministic no-live-service checks: fake claude, mock MCP, no real tokens.
- Real Claude provider invocation, Jira transitions, and GitHub release publishing are excluded from ordinary CI.
- Future secret-backed CI environment for live smoke tests requires a separate decision with explicit design for secrets management, token rotation, environment isolation, and blast-radius containment. This is deferred, not rejected.

## Consequences

- Every PR must pass CI before merge. This adds process but eliminates the "forgot to run tests" failure mode.
- The test suite (`bash tests/run_tests.sh`) becomes the CI entry point. CI must not bypass or weaken it.
- External-system integration testing is deferred to smoke/manual gates until a secret-backed CI environment is designed.
- The isolated Claude runtime work already moves the project toward CI-ready determinism — this ADR formalizes that direction.
- Release documentation and confidence reporting become structured (gate status, commit/tag, tests run, residual risk) rather than informal.
