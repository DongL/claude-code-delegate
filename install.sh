#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${CLAUDE_DELEGATE_INSTALL_DIR:-$HOME/.claude-code-delegate}"
REPO_URL="https://github.com/DongL/claude-code-delegate.git"

# ---- uninstall ----
if [ "${1:-}" = "--uninstall" ]; then
  echo "==> Uninstalling claude-code-delegate..."

  for d in "$HOME/.agents/skills/claude-code-delegate" "$HOME/.codex/skills/claude-code-delegate"; do
    if [ -L "$d" ] || [ -e "$d" ]; then
      rm -f "$d"
      echo "  Removed $d"
    fi
  done

  if [ "${2:-}" = "--keep-repo" ]; then
    echo "  Keeping repo at $INSTALL_DIR"
  elif [ -d "$INSTALL_DIR" ]; then
    echo "  Removing repo at $INSTALL_DIR..."
    rm -rf "$INSTALL_DIR"
  fi

  if [ "${CLAUDE_DELEGATE_SKIP_MCP:-0}" != "1" ] && python3 -c "import mcp" 2>/dev/null; then
    echo "  mcp package remains installed. Remove with: pip3 uninstall mcp"
  fi

  echo "==> Uninstall complete."
  exit 0
fi

# ---- install ----
echo "==> Installing claude-code-delegate..."

command -v git >/dev/null 2>&1 || { echo "ERROR: git is required"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 is required"; exit 1; }
echo "  [OK] git and python3 found"

if [ -d "$INSTALL_DIR" ]; then
  echo "  Updating existing install at $INSTALL_DIR..."
  git -C "$INSTALL_DIR" pull --ff-only
else
  echo "  Cloning to $INSTALL_DIR..."
  git clone "$REPO_URL" "$INSTALL_DIR"
fi

mkdir -p "$HOME/.agents/skills"
ln -sfn "$INSTALL_DIR" "$HOME/.agents/skills/claude-code-delegate"
echo "  [OK] Symlinked to ~/.agents/skills/claude-code-delegate"

mkdir -p "$HOME/.codex/skills"
ln -sfn "$INSTALL_DIR" "$HOME/.codex/skills/claude-code-delegate"
echo "  [OK] Symlinked to ~/.codex/skills/claude-code-delegate"

echo "  Running tests..."
bash "$INSTALL_DIR/tests/run_tests.sh" || echo "  [WARN] Some tests failed — check the output above"

if [ "${CLAUDE_DELEGATE_SKIP_MCP:-0}" != "1" ]; then
  if python3 -c "import mcp" 2>/dev/null; then
    echo "  [OK] mcp package already installed"
  else
    echo "  Installing mcp package for MCP server support..."
    pip3 install mcp 2>/dev/null || echo "  [WARN] mcp install failed — MCP server requires: pip install mcp"
  fi
fi

echo ""
echo "==> Installation complete!"
echo ""
echo "Provider setup (required before first use):"
echo "  1. Get a DeepSeek API key: https://platform.deepseek.com/api_keys"
echo "  2. Add to your shell profile (~/.zshrc or ~/.bashrc):"
echo ""
echo "     export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic"
echo "     export ANTHROPIC_AUTH_TOKEN=<your-key>"
echo "     export ANTHROPIC_MODEL=deepseek-v4-pro[1m]"
echo "     export ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-pro[1m]"
echo "     export ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-pro[1m]"
echo "     export ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-flash[1m]"
echo "     export CLAUDE_CODE_SUBAGENT_MODEL=deepseek-v4-flash[1m]"
echo "     export CLAUDE_CODE_EFFORT_LEVEL=max"
echo ""
echo "  3. Verify: claude -p 'hello' --model deepseek-v4-flash[1m]"
echo ""
echo "MCP server setup (optional):"
echo "  Add to your project .mcp.json or Codex MCP config:"
echo '  {"mcpServers":{"claude-code-delegate":{"command":"python3","args":["$HOME/.claude-code-delegate/scripts/mcp_server.py"]}}}'
echo ""
echo "Quick test:"
echo "  $INSTALL_DIR/scripts/run-claude-code.sh --interactive --flash 'hello from delegate'"
