#!/usr/bin/env python3
"""Convert Markdown text to Jira-safe plain text.

Strips Markdown formatting characters that render literally in Jira MCP's
plain-text comment body, preserving readability and list structure.
"""

from __future__ import annotations

import re
import sys


def markdown_to_plain(text: str) -> str:
    """Strip Markdown syntax and return Jira-safe plain text."""

    # Remove fenced code blocks (keep content)
    text = re.sub(r'```[^\n]*\n(.*?)```', r'\1', text, flags=re.DOTALL)

    # Inline code backticks
    text = re.sub(r'`([^`]+)`', r'\1', text)

    # Images: ![alt](url) -> alt (must run before links)
    text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', text)

    # Links: [text](url) -> text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)

    # Bold: **text** or __text__
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'__([^_]+)__', r'\1', text)

    # Italic: *text* or _text_ (but not bullet `* `)
    text = re.sub(r'(?<!\*)\*([^*\n]+)\*(?!\*)', r'\1', text)
    text = re.sub(r'(?<!_)_([^_\n]+)_(?!_)', r'\1', text)

    # Strikethrough: ~~text~~
    text = re.sub(r'~~([^~]+)~~', r'\1', text)

    # ATX headings: keep text, drop # markers
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)

    # Checked task: - [x] -> - (done)
    text = re.sub(r'^(\s*)- \[x\] ', r'\1- (done) ', text, flags=re.MULTILINE)

    # Unchecked task: - [ ] -> -
    text = re.sub(r'^(\s*)- \[ \] ', r'\1- ', text, flags=re.MULTILINE)

    # Horizontal rules
    text = re.sub(r'^[-*_]{3,}\s*$', '---', text, flags=re.MULTILINE)

    # Blockquotes: drop > prefix, keep content
    text = re.sub(r'^>\s?', '', text, flags=re.MULTILINE)

    # Collapse consecutive blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.rstrip()


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print("Usage: jira_safe_text.py [TEXT]")
        print("       echo 'markdown' | jira_safe_text.py")
        print()
        print("Convert Markdown to Jira-safe plain text by stripping")
        print("formatting characters that render literally in Jira MCP.")
        return 0

    if len(sys.argv) > 1 and sys.argv[1] != "-":
        text = " ".join(sys.argv[1:])
    else:
        text = sys.stdin.read()

    print(markdown_to_plain(text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
