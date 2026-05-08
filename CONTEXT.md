# Claude Code Delegator Glossary

## Orchestrator

The entity that owns the planning and review phases of the delegation workflow. May be an AI (Codex, Claude Code, Cursor, etc.) or a human. The orchestrator produces a plan, invokes Claude Code for execution, then inspects the results.

Not to be confused with "Executor" (Claude Code), which only implements and verifies.

## Executor

Claude Code, acting on a concrete plan supplied by the Orchestrator. The Executor does not design — it reads context, implements, runs verification commands, and reports results.

## Delegation

The act of the Orchestrator handing a bounded implementation task to the Executor, with explicit ownership boundaries and verification criteria.

## Provider Model

The model name passed to Claude Code (e.g., `deepseek-v4-pro[1m]`). This is not a standard Anthropic model ID — it reflects the custom provider/backend that the target Claude Code installation is configured to use. The Orchestrator knows what model its Claude Code instance can serve. The wrapper defaults to `deepseek-v4-pro[1m]` but is overridable via `CLAUDE_DELEGATOR_MODEL`.

## Correction Iteration

The practice of repeating correction passes until the diff is correct, rather than limiting to a fixed number of attempts. Each pass is surfaced to the user so they can intervene if convergence stalls.
