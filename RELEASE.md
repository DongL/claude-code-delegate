# Release Readiness Checklist

## Blocking Gates

All gates must pass before tagging a release. If a gate does not apply,
note the reason and move to the next.

- [ ] Default CI passes: bash tests/run_tests.sh
- [ ] Quality gate passes: bash scripts/quality-gate.sh
- [ ] Release gate report passes: bash scripts/release-gate-report.sh
- [ ] Smoke tests pass (if live credentials available):
      CLAUDE_DELEGATE_SMOKE_TEST=1 bash scripts/run-smoke-tests.sh
- [ ] Docs/behavior reconciliation: ADRs, README, SKILL.md, and code agree
      on all documented behaviors (subagent mode, secret-free config, etc.)
- [ ] Install verification: pip install -e . succeeds
- [ ] .mcp.json contains no committed secrets
- [ ] VERSION bump (pyproject.toml) matches semver

## Compatibility Matrix

| Platform | Supported | Notes |
|----------|-----------|-------|
| macOS 12+ | Yes | Primary development platform |
| Linux (x86_64) | Yes | CI runs on ubuntu-latest |
| Windows | No | Not tested |

| Python | Supported | Notes |
|--------|-----------|-------|
| 3.10 | Yes | Minimum requirement |
| 3.11 | Yes | Tested in CI |
| 3.12 | Yes | Tested in CI |

| Executor | Supported | Notes |
|----------|-----------|-------|
| Claude Code CLI | Yes | Default executor |
| OpenCode CLI | Yes | Via --opencode or CLAUDE_DELEGATE_EXECUTOR |

| Model Provider | Supported | Notes |
|----------------|-----------|-------|
| DeepSeek V4 (API) | Yes | Default provider |
| Anthropic (API) | Yes | Via native Claude Code |
| OpenCode Zen | Yes | For OpenCode backend |

## Release Process

1. Run all blocking gates above
2. Bump version in pyproject.toml
3. Update CHANGELOG.md
4. Tag release: git tag v$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
5. Push tag: git push origin v$(...)
6. Create GitHub release with changelog notes
