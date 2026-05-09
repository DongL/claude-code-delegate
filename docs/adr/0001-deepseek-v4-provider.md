# Use DeepSeek V4 via cc-switch as the default provider

The Claude Code Delegate defaults to DeepSeek V4 models (`deepseek-v4-pro[1m]` for primary reasoning, `deepseek-v4-flash` for subagent/fast tasks) routed through Claude Code via [`cc-switch`](https://github.com/farion1231/cc-switch). This decision is driven by cost and availability: DeepSeek V4 provides competitive reasoning capability at significantly lower cost than Anthropic direct API, and `cc-switch` abstracts provider configuration so the wrapper doesn't need to manage provider-specific credentials or base URLs.

## Status

Accepted

## Considered Options

- **Anthropic direct API** — standard choice but higher cost and regional availability constraints. The project's wrapper is provider-agnostic via `CLAUDE_DELEGATE_MODEL`, so switching back requires only an env var change.
- **Other third-party providers** — not evaluated; `cc-switch` makes provider rotation a local configuration concern rather than a project-level decision.
- **Single model tier** — rejected because different tasks have different cost/latency requirements. Pro for architecture and debugging, Flash for simple edits and subagents.

## Risk: Provider Availability

The repair layer depends on external LLM providers, with availability failures possible at multiple layers:

1. Upstream model API throttling or overload (HTTP 429, 500, 503).
2. Provider authentication, billing, quota, or model-alias changes.
3. Third-party relay/proxy outage or degraded routing, when a relay is used.
4. Local provider-switching misconfiguration (stale env vars, wrong base URL, invalid API key).
5. Regional, commercial, or policy-based availability constraints.

**Mitigation** (not elimination):
- Retry transient 429/5xx errors with bounded exponential backoff.
- Use Flash for low-risk subagent tasks and Pro for primary reasoning.
- Maintain at least one configured fallback provider profile via `cc-switch`.
- Surface clear diagnostics on provider error — never hide provider errors behind generic failure messages.
- Provide manual override through `CLAUDE_DELEGATE_MODEL`.

This is classified as risk accepted with mitigation, not merely acknowledged. The provider layer must fail closed, preserve the working tree, and surface an actionable diagnostic.

## Consequences

- The wrapper defaults (`run-claude-code.sh`) contain non-standard model IDs, which may confuse first-time GitHub visitors. Mitigated by `CLAUDE_DELEGATE_MODEL` override documentation and the model table in SKILL.md.
- `[1m]` suffix on model names is a context-window routing label (1M tokens), not a capability tier — must not be confused with the Pro/Flash distinction.
- Thinking budget (`--effort`) is orthogonal to model tier: `effort=max` on Flash does not equal Pro capability.
- No provider lock-in: the wrapper only references models via `--model` flag and env var; changing provider requires only `cc-switch` and a `CLAUDE_DELEGATE_MODEL` override.
