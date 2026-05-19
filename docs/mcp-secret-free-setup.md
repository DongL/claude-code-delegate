# Secret-Free MCP Configuration

The project .mcp.json must contain zero secrets. Secrets belong in user-level
configuration. Three methods are supported for supplying credentials to MCP
servers without committing them to the repository.

## Method 1: Environment Variable Expansion

Reference env vars in .mcp.json using ${VAR_NAME} syntax:

```json
{
  "mcpServers": {
    "jira": {
      "command": "node",
      "args": ["jira-mcp-server/index.js"],
      "env": {
        "JIRA_BASE_URL": "${JIRA_BASE_URL}",
        "JIRA_USER_EMAIL": "${JIRA_USER_EMAIL}",
        "JIRA_API_TOKEN": "${JIRA_API_TOKEN}"
      }
    }
  }
}
```

The MCP host expands these from the shell environment before launching the
server. Set them in your .bashrc, .zshrc, or session:

```bash
export JIRA_BASE_URL="https://your-domain.atlassian.net"
export JIRA_USER_EMAIL="your-email@example.com"
export JIRA_API_TOKEN="your-api-token"
```

## Method 2: User-Level MCP Configuration

Place server definitions with embedded secrets in user-level config, not the
project .mcp.json:

- ~/.claude/mcp.json
- ~/.config/opencode/mcp.json

The project .mcp.json should reference servers by name only without env vars
that contain secrets. The MCP host merges project and user configs.

## Method 3: .env File with Git-Ignored Secrets

Create env/.env (gitignored by default) with credentials:

```
JIRA_BASE_URL=https://your-domain.atlassian.net
JIRA_USER_EMAIL=your-email@example.com
JIRA_API_TOKEN=your-api-token
```

Source it before launching the MCP host:

```bash
set -a; source env/.env; set +a
```

## Verification

The project includes a test that .mcp.json contains no literal secret values.
Run it with:

```bash
bash tests/run_tests.sh
```

Look for "mcp.json has no committed secrets" in the test output.
