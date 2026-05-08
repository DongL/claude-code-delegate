# Safe Jira MCP Discovery and Credential Handling

## Overview

This document describes how to safely inspect Jira MCP configuration in this project, what to report, and what to keep confidential. It also documents the plaintext credential risk introduced by storing API tokens in MCP config files, and recommended mitigations.

## Safe Discovery Pattern

When discovering Jira MCP server configuration, report only:

1. **Server key** — e.g., `jira`
2. **Command** — e.g., `node`
3. **Args shape** — the *form* of the arguments, not their values (e.g., `["/path/to/jira-mcp/build/index.js"]`)
4. **Environment variable names** — the *names* of the env vars, not their values (e.g., `JIRA_BASE_URL`, `JIRA_USER_EMAIL`, `JIRA_API_TOKEN`)

**Never print, echo, log, or return the values of any environment variables, especially `JIRA_API_TOKEN`.**

### Example of safe discovery output

```
Jira MCP server found:
  key: jira
  command: node
  args: ["/path/to/jira-mcp/build/index.js"]
  env vars: JIRA_BASE_URL, JIRA_USER_EMAIL, JIRA_API_TOKEN
```

### Example of unsafe discovery (DO NOT DO)

```
Jira MCP server found:
  key: jira
  command: node
  args: ["/path/to/jira-mcp/build/index.js"]
  env: {
    "JIRA_BASE_URL": "https://dongliang.atlassian.net",     # OK to show base URL
    "JIRA_USER_EMAIL": "user@example.com",                   # OK for shared projects
    "JIRA_API_TOKEN": "ATATT3xFfGF0..."                      # NEVER show this
  }
```

## Plaintext Token Risk

The Jira MCP configuration in `~/.claude/mcp.json` stores the `JIRA_API_TOKEN` in **plaintext**. This creates the following risks:

| Risk | Impact |
|------|--------|
| File access leak | Anyone with read access to the file can use the token to call the Jira API as the configured user |
| Backup exposure | Backups of the home directory include the plaintext token |
| Clipboard/display | Screen sharing, logging, or debugging output may expose the value |
| Version control | Accidental commit of `mcp.json` to a repository exposes the credential permanently |

## Recommended Mitigation

### Option 1: Use shell env var expansion (recommended)

Claude Code supports `env` variable expansion in `mcp.json`. Store the token in an environment variable sourced from a protected file:

1. Remove the `JIRA_API_TOKEN` value from `~/.claude/mcp.json`.
2. Add it to a `~/.claude/.env` file with restricted permissions (e.g., `chmod 600`):
   ```
   JIRA_API_TOKEN=ATATT3x...
   ```
3. Reference the env var in `~/.claude/mcp.json` (Claude Code or MCP host resolves `${JIRA_API_TOKEN}` automatically).

### Option 2: Use macOS Keychain

Use the `security` command to store and retrieve the token:

```bash
# Store once
security add-generic-password -s "jira-mcp-token" -a "$USER" -w "ATATT3x..."

# Reference in a wrapper script or shell profile
export JIRA_API_TOKEN=$(security find-generic-password -s "jira-mcp-token" -a "$USER" -w)
```

### Option 3: Remove from project `.mcp.json`

The project-level `.mcp.json` should never contain credentials. The Jira MCP server was already removed from the project's `.mcp.json` — credentials belong in `~/.claude/mcp.json` (user-level config, still plaintext but not committed to version control).

## Verification

After applying any mitigation, verify:

1. `~/.claude/mcp.json` no longer contains a plaintext `JIRA_API_TOKEN` value.
2. Jira MCP operations still work (run a test query like fetching an issue).
3. No credential values appear in logs, stdout, stderr, or discovery output.

## References

- [Claude Code MCP Configuration](https://docs.anthropic.com/en/docs/claude-code/mcp)
- [Jira REST API authentication](https://developer.atlassian.com/cloud/jira/platform/basic-auth-for-rest-apis/)
