"""Structured error diagnostics for delegation pipeline."""

from __future__ import annotations

from typing import Any


class DelegationError(Exception):
    def __init__(
        self,
        error_code: str,
        message: str,
        resolution_hint: str = "",
        sanitized_context: dict[str, Any] | None = None,
    ):
        self.error_code = error_code
        self.message = message
        self.resolution_hint = resolution_hint
        self.sanitized_context = sanitized_context or {}
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": self.message,
            "resolution_hint": self.resolution_hint,
            "sanitized_context": self.sanitized_context,
        }


# Error codes
ERR_CLAUDE_NOT_FOUND = "CLAUDE_NOT_FOUND"
ERR_PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
ERR_MCP_CONFIG = "MCP_CONFIG_ERROR"
ERR_AUTH_FAILED = "AUTH_FAILED"
ERR_PIPELINE_INTERNAL = "PIPELINE_INTERNAL"
ERR_EMPTY_PROMPT = "EMPTY_PROMPT"

RESOLUTION_HINTS: dict[str, str] = {
    ERR_CLAUDE_NOT_FOUND: (
        "Claude Code CLI is not on PATH or not installed. "
        "Install Claude Code or set executor=opencode."
    ),
    ERR_PROVIDER_UNAVAILABLE: (
        "The model provider returned an error. "
        "Check ANTHROPIC_BASE_URL and ANTHROPIC_AUTH_TOKEN are set correctly."
    ),
    ERR_MCP_CONFIG: (
        "MCP configuration could not be loaded. "
        "Check the requested server exists in .mcp.json or CLAUDE_DELEGATE_MCP_CONFIG_PATH."
    ),
    ERR_AUTH_FAILED: (
        "Authentication failed. "
        "Check API tokens are valid and not expired."
    ),
    ERR_PIPELINE_INTERNAL: (
        "An unexpected pipeline error occurred. "
        "Set CLAUDE_DELEGATE_LOG_LEVEL=DEBUG for details."
    ),
    ERR_EMPTY_PROMPT: (
        "The prepared prompt is empty. "
        "The classification or template builder may have failed."
    ),
}


def classify_stderr_error(stderr: str) -> str:
    stderr_lower = stderr.lower()
    if "auth" in stderr_lower or "token" in stderr_lower or "unauthorized" in stderr_lower:
        return ERR_AUTH_FAILED
    if "provider" in stderr_lower or "model" in stderr_lower or "not found" in stderr_lower:
        return ERR_PROVIDER_UNAVAILABLE
    if "mcp" in stderr_lower or "config" in stderr_lower:
        return ERR_MCP_CONFIG
    return ERR_PIPELINE_INTERNAL


def build_error_from_stderr(
    stderr: str,
    returncode: int,
) -> DelegationError:
    error_code = classify_stderr_error(stderr)
    hint = RESOLUTION_HINTS.get(error_code, "")
    sanitized = {
        "returncode": returncode,
        "stderr_length": len(stderr),
    }
    msg = stderr.strip()[:200] if stderr else "Unknown error"
    return DelegationError(
        error_code=error_code,
        message=msg,
        resolution_hint=hint,
        sanitized_context=sanitized,
    )
