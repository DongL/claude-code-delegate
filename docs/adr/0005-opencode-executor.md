# 0005: OpenCode as a second executor backend

Add OpenCode (`opencode run`) as an alternative executor backend alongside Claude Code (`claude -p`). The pipeline supports two executor branches: the original `claude-code` path and a new `opencode` path. Selection is per-invocation via `--executor opencode`, `--opencode` shorthand, or `CLAUDE_DELEGATE_EXECUTOR` environment variable.

## Status

Accepted

## Context

The claude-code-delegate pipeline was designed around a single executor: Claude Code. Every delegation runs `claude -p` with model, effort, permission, and MCP flags. This has worked since the project's inception, but two pressures emerged:

1. **Anthropic dependency**: Claude Code requires an Anthropic API key. Users who want open-source models (DeepSeek, Qwen) or operate in air-gapped environments cannot use the delegation pipeline at all.

2. **Toolchain duplication**: Several users run OpenCode as their primary coding agent. Maintaining a separate Claude Code installation solely for delegation is friction — they want one agent that handles both interactive and delegated work.

Adding OpenCode as a second executor removes the Anthropic gate and consolidates the toolchain. The pipeline architecture (classify → envelope → invoke → compact → profile) is executor-agnostic. Only the invocation and output-parsing stages differ between backends.

## Architecture

The pipeline forks at two points: subprocess invocation and output parsing.

```
                                ┌──────────────────────────────┐
                                │       run_delegation_        │
                                │       pipeline()             │
                                │                              │
                                │   classify_prompt()          │
                                │   build_prepared_prompt()    │
                                └──────────┬───────────────────┘
                                           │
                                           │ InvokerConfig.executor
                                           │ ("claude-code" | "opencode")
                                           ▼
                    ┌──────────────────────────────────────────┐
                    │            invoke_claude()                │
                    │              (dispatcher)                 │
                    │                                          │
                    │  if executor == "claude-code"             │
                    │    → _invoke_claude_code()                │
                    │       claude -p --model M --effort E ...  │
                    │       --permission-mode bypassPermissions │
                    │       --output-format stream-json         │
                    │       --mcp-config ...                    │
                    │       --disallowedTools Task Agent        │
                    │                                          │
                    │  if executor == "opencode"                │
                    │    → _invoke_opencode()                   │
                    │       opencode run --format json          │
                    │        --model provider/model             │
                    │        --dangerously-skip-permissions     │
                    │        (no --effort, no --mcp-config,     │
                    │         no --disallowedTools)             │
                    └──────────────────┬────────────────────────┘
                                       │
                                       ▼
                    ┌──────────────────────────────────────────┐
                    │        parse_compact_output()             │
                    │                                          │
                    │  Detects format:                          │
                    │  - JSON object → Claude Code result       │
                    │  - NDJSON with text/step_finish/error     │
                    │    events → OpenCode result               │
                    │    (concatenates text events, extracts    │
                    │     tokens from step_finish, surfaces     │
                    │     error events as is_error)             │
                    └──────────────────────────────────────────┘
                                       │
                                       ▼
                    ┌──────────────────────────────────────────┐
                    │         DelegationResult                  │
                    │  { result, usage, cost_usd, ... }         │
                    └──────────────────────────────────────────┘
```

The heartbeat/monitor thread runs identically in both branches. The OpenCode variant omits `effort` from heartbeat messages (OpenCode has no effort concept) and uses `mode` instead.

## Decisions

### D1: Model mapping via CLAUDE_CODE_MODEL_MAP

OpenCode uses `provider/model` format (`deepseek/deepseek-v4-flash`). Claude Code uses short names (`deepseek-v4-flash[1m]`). A static dictionary maps the 8 most common Claude Code model IDs to OpenCode equivalents.

Unmapped models fall back to `deepseek/{base}`. This is a reasonable default because most custom providers in this deployment chain are DeepSeek-based. If a non-DeepSeek provider is needed, the user passes the full `provider/model` string (which contains `/` and passes through unmapped).

The `[1m]` context-window suffix is stripped during normalization (`_normalize_model()`) so that `deepseek-v4-pro[1m]` matches the map key `deepseek-v4-pro`.

### D2: Event format parsing

Claude Code emits a single JSON object (quiet mode) or newline-delimited stream-json events (stream mode). OpenCode emits newline-delimited events with a different schema: `{"type": "text", "part": {"type": "text", "text": "..."}}`, `{"type": "step_finish", "part": {"tokens": {...}, "cost": N}}`, and `{"type": "error", "error": {"data": {"message": "..."}}}`.

`parse_compact_output()` detects the format heuristically: if any event has `type == "text"`, `type == "error"`, or `type == "step_finish"`, it treats the stream as OpenCode format. It concatenates all `text` event parts into the result string and extracts usage from the last `step_finish` event.

This detection is reliable because:
- Claude Code never emits events with `type: "text"`.
- OpenCode always emits at least one `text` event before `step_finish`.
- A malformed or empty stream triggers neither format and returns an empty result (same behavior as before).

### D3: Heartbeat with CPU stall detection

The heartbeat logic is duplicated between `invoker.py` and `opencode_invoker.py` rather than shared. Both versions are structurally identical (same CPU polling via `ps`, same stall detection, same SIGTERM→SIGKILL escalation) but differ in:
- The stderr prefix text (`"Claude Code still running:"` vs `"OpenCode still running:"`).
- The key-value pairs omitted (`effort` in OpenCode, included in Claude Code).
- The `mcp_mode` field format (no MCP config for OpenCode).

Duplication is intentional: sharing via a parameterised helper would require threading a variable number of display fields through a common interface, adding complexity for no operational benefit. The two copies are short (~70 lines each) and change infrequently.

### D4: Permission bridging

Claude Code uses `--permission-mode bypassPermissions`. OpenCode uses `--dangerously-skip-permissions`. Both express the same intent: run non-interactively without approval prompts.

The mapping happens inside `build_opencode_args()` in `opencode_invoker.py`. The `InvokerConfig.permission_mode` field is shared across both backends; only the CLI flag translation differs. This avoids duplicating the permission resolution logic that flows through `pipeline.py` → `invoker.py`.

Other permission modes (`acceptEdits`, `bypassApprovals`) are not mapped because OpenCode does not support a `--permission-mode` flag. Only `bypassPermissions` (the default mode used by the delegation pipeline) is bridged.

### D5: No --agent flag for subagent_mode

Claude Code controls subagent spawning via `--disallowedTools "Task Agent"` (off) or default behavior (on). OpenCode does not have an `--agent` equivalent. The `subagent_mode` field is accepted in `OpenCodeInvokerConfig` but deliberately not mapped — no `--agent` flag is added to the `opencode run` command.

Rationale:
- Adding a hypothetical `--agent` flag would be implementing a feature that does not exist in the target tool.
- OpenCode's default behavior is to allow subagents. Users who want subagents off when using OpenCode must disable them via OpenCode's own configuration, not through the delegation pipeline.
- If OpenCode later adds subagent control, this decision can be revisited with a single code change.

### D6: Environment config bridging

Claude Code reads settings from `~/.claude/settings.json` and `~/.claude/settings.local.json`. OpenCode reads from `~/.config/opencode/config.json`, `./opencode.json`, and `./opencode.jsonc`. Each backend's env loader (`load_claude_settings_env()` vs `load_opencode_env()`) reads only its own config files.

Both backends share the parent process environment (via `dict(base_env or os.environ)`). The OpenCode backfill adds env keys from config files with `setdefault` semantics, preserving explicit overrides just as the Claude Code backfill does.

OpenCode config files are scanned in order (user config → user local → project json → project jsonc). The first file found with an `env` dict is used. This means per-project `opencode.json[c]` takes precedence over global config, matching OpenCode's own precedence rules.

### D7: QWEN_MODEL as third classifier tier

The classifier gained a third model tier (`qwen` → `QWEN_MODEL = "opencode/qwen3.6-plus-free"`) alongside `flash` and `pro`. This is not executor-specific — it defines a model string that happens to be an OpenCode-compatible provider. Users on the `claude-code` executor who specify `--qwen` will have this model string passed to `claude -p`, which will fail unless their Claude Code provider supports the OpenCode format.

This is a known asymmetry. The Qwen tier exists because it is the preferred free-tier model for OpenCode users. Claude Code users on the same project should not specify `--qwen`. The alternative — making `QWEN_MODEL` executor-aware — would add conditional logic to a pure classification function that currently has no executor awareness.

## Trade-offs

### Gained

- **No Anthropic dependency**: The full delegation pipeline works without an Anthropic API key.
- **Single toolchain**: Users who already run OpenCode do not need a separate Claude Code installation.
- **Backward compatible**: `executor="claude-code"` is the default. Existing invocations and configurations are unchanged.
- **Shared pipeline**: Classification, prompt preparation, output compaction, and profile logging are identical across backends. The executor branch affects only invocation and parsing — ~200 lines of new code.
- **Per-invocation selection**: Orchestrators can route expensive tasks to Claude Code and cheap tasks to OpenCode within the same session.

### Lost

- **No effort control**: OpenCode does not support `--effort`. Users who rely on per-task reasoning budgets lose this dimension when using the OpenCode backend. Mitigation: the model provider can be configured with a fixed reasoning budget independently.
- **No MCP config passing**: OpenCode does not support `--mcp-config` or `--strict-mcp-config`. Delegations that require specific MCP servers must configure them through OpenCode's own config files. This is a significant gap if the orchestrator dynamically selects MCP servers per task.
- **No subagent control**: The pipeline cannot disable subagents in OpenCode. Users who want subagents off must configure this outside the delegation pipeline.
- **No stream-json output**: OpenCode's event stream is parsed post-hoc. Real-time streaming is not supported for the OpenCode backend.
- **Model map maintenance**: `CLAUDE_CODE_MODEL_MAP` is a static dictionary that must be updated when new model IDs are added. It is not auto-discovered from either backend.
- **Duplicated heartbeat**: Two copies of the monitor loop (one per backend) must be kept in sync when changes are made.

## Open Questions

### OQ1: subagent_mode=on behavior

When `subagent_mode="on"` and `executor="opencode"`, the pipeline currently takes no action (no `--agent` flag, no `--disallowedTools`). OpenCode's default behavior allows subagents. Is this the desired behavior, or should the pipeline actively signal "subagents allowed" in case OpenCode later adds a flag for it?

Current stance: do nothing until OpenCode adds explicit subagent control. The "on" case matches the default, so no action is needed.

### OQ2: ALLOWED_MODELS future use

`opencode_invoker.py` declares `ALLOWED_MODELS: frozenset[str] = frozenset()` with no current usage. `_validate_model()` checks `if not ALLOWED_MODELS` and skips validation. What is the intended use case?

Three candidates:
1. An allowlist of permitted OpenCode models, enforced at invocation time.
2. A set of models the orchestrator supports, used for capability advertisement.
3. A configurable override that replaces the static model map.

Until a concrete use case emerges, the frozenset remains empty and inert.

### OQ3: Effort mapping for OpenCode

OpenCode does not accept `--effort`, but some providers support reasoning budgets via model suffix (e.g., `deepseek/deepseek-chat` with a thinking parameter). Should the pipeline translate effort values into provider-specific configurations?

Current stance: no. Effort semantics vary widely across providers. A translation layer would require provider-specific knowledge that belongs in OpenCode, not in the delegation pipeline. If a user needs a specific reasoning configuration, they should configure it at the provider level and pass the model string directly.

## Consequences

- Pipeline callers can pass `executor="opencode"` to use the alternative backend without changing any other parameter.
- The classifier gains `QWEN_MODEL` as a third tier, used when `model_tier == "qwen"`.
- `run-pipeline.py` gains an `executor` positional argument (6th or 7th positional, depending on invocation mode).
- The shell wrapper (`run-claude-code.sh`) gains `--opencode` and `--executor` flags.
- `CLAUDE_DELEGATE_EXECUTOR` env var is documented in README and CONTEXT.md.
- The test suite must cover both executor paths, including the OpenCode event format parser.
