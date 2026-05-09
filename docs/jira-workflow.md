# Jira Workflow

When delegating Jira-related tasks to Claude Code, the following conventions apply.

## Comment Formatting

The Jira MCP `add_comment` tool accepts a plain text body, not Markdown. Markdown control characters are displayed literally. Write comments as plain readable text:

- Do not use `**bold**`, `*italic*`, backticks, fenced code blocks, Markdown tables, or `[links](url)` syntax.
- Do not use task list syntax (`- [ ]`, `- [x]`).
- Use simple `-` bullet lists and indentation for structure (hyphen lists display cleanly as plain text).
- For inline code references, use plain quotes or parentheses instead of backticks.
- For emphasis, use natural language phrasing rather than bold/italic markers.
- Keep full Markdown formatting for responses to the user — this rule applies only to issue tracker comments.

### jira-safe-text.py

The bundled `scripts/jira-safe-text.py` utility converts Markdown text to Jira-safe plain text:

```bash
echo "**bold** and *italic*" | "$CLAUDE_DELEGATE_DIR/scripts/jira-safe-text.py"
# Output: bold and italic
```

## Duplicate Search Failure

When delegating Jira issue creation, the prompt must instruct Claude Code: if the Jira MCP search endpoint is deprecated, unavailable, or returns an error, the tool must report the failure explicitly and must not claim that duplicates were avoided. If issue creation proceeds despite the unavailable search, the output must label the issue's duplicate status as unverified.
