# Changelog

## v1.7.0 (2026-05-19)

### Features
- feat: production readiness — pyproject.toml, diagnostics, audit logging, smoke tests, release checklist, ADRs 0006-0007 (#42)

### Documentation
- docs: fix README formatting — line-break OpenCode Zen notes
- docs: note OpenCode Zen has only 1 DeepSeek model (free beta)
- docs: fix Manual install section — add all 3 symlinks and Update subsection

### Bug Fixes
- fix: remove broken --agent flag from opencode invoker (#40)
- fix: revert OpenCode flash mapping to deepseek/deepseek-v4-flash
- fix: map --flash to deepseek-v4-flash-free for Claude Code and OpenCode

### Key Changes
- **Packaging**: pyproject.toml with setuptools build, PyPI metadata, optional MCP extras
- **Diagnostics**: `diagnostics.py` module with delegation error classification, resolution hints
- **Audit Logging**: structured audit records written to configurable log file
- **Smoke Tests**: guarded smoke test lane (CCDM-41) requiring explicit env var
- **Release Checklist**: `RELEASE.md` with blocking gates and compatibility matrix
- **ADRs 0006-0007**: async delegation architecture (0006), release process (0007)
- **CI/CD Quality Gates**: GitHub Actions workflow, `quality-gate.sh`, `release-gate-report.sh`
- **OpenCode Docs**: executor docs updated, conversational delegation guide
