# Use async delegation leases for long-running Claude Code invocations

Long-running Claude Code invocations can still be valid work. The orchestrator cannot reliably infer "stuck" from elapsed time alone. Killing or abandoning a running invocation and starting a reduced correction plan wastes tokens and can create competing changes that conflict with work the original invocation may still be completing. This ADR introduces async delegation leases: a `--start` / `--poll` contract with single-flight semantics that gives running jobs exclusive execution rights until the detached supervisor writes a terminal result.

## Status

Accepted (2026-05-13)

## Considered Options

- **Synchronous-only wrapper for all work** — the simplest model: every delegation blocks until Claude Code exits. This works for short tasks but forces the orchestrator to hold a connection open indefinitely for long-running work. If the orchestrator times out or is interrupted, it has no way to discover whether the delegation completed or what its result was. Rejected: the orchestrator needs the ability to launch and check later without maintaining a persistent connection.

- **Hard timeout or no-progress timeout as the primary solution** — kill the subprocess after wall-clock or CPU-stall threshold, then fall back to a correction plan. This addresses the orchestrator's "is it stuck?" question but at the cost of aborting work that may still be productive. A no-progress timeout is available as a configurable safeguard via `CLAUDE_DELEGATE_INACTIVITY_TIMEOUT_SECONDS`, but it is a safety net, not the primary mechanism. Rejected as primary: the default should preserve running work, not guess when to give up.

- **Daemon-thread waiter inside the `--start` process** — the process that calls `--start` spawns a background thread that waits for Claude Code and writes the result. This keeps the result-collection logic in-process but ties job completion to the lifetime of the `--start` process. If the `--start` process crashes or is killed before the thread finishes, the result is lost and the delegated Claude Code becomes an orphan. Rejected: the supervisor must survive the `--start` process.

- **Async delegation leases with detached supervisor (accepted)** — a `--start` flag launches a background delegation and returns a `job_id` immediately. A detached supervisor process (`--supervise <job_id>`) launches Claude Code, waits for it, and writes `result.json` with the real returncode. Polling (`--poll <job_id>`) reads persisted job state instead of relying on in-memory process state. Single-flight semantics prevent duplicate delegations: a running job owns exclusive execution, and second `--start` calls return `lease_held`. This is the accepted option.

## Decision

Implement async delegation with the following design:

1. **`--start` launches a background delegation.** The wrapper calls `start_delegation_async()` in the pipeline, which spawns a detached supervisor subprocess (`run-pipeline.py --supervise <job_id>`), writes job metadata to `.claude-delegate/runtime/jobs/<job_id>/meta.json`, and returns JSON with `job_id` and `status: running`. The supervisor process is detached via `start_new_session=True` with stdin/stdout/stderr piped to `/dev/null`, so it survives the `--start` process's exit.

2. **`--poll <job_id>` checks persisted job state.** The wrapper calls `poll_delegation_status()`, which reads `meta.json` and `result.json` from the job directory. The supervisor process writes `result.json` with the real returncode once Claude Code exits. Polling never checks in-memory state or process tables for the delegation outcome — it reads files.

3. **Single-flight lease semantics.** `start_delegation_async()` calls `find_active_lease()` before creating any new job. If a job with `status: running` and an alive PID is found, the call returns `status: lease_held` with the existing job's `job_id` and a message that no retry, reduced correction plan, or second delegation is allowed while the original job is still running. This is enforced at the pipeline entry point, before any classification or subprocess launch.

4. **Lease detection uses PID aliveness.** `find_active_lease()` iterates job directories in reverse creation order, reads each `meta.json`, checks `status == "running"`, and calls `os.kill(pid, 0)` to verify the PID is alive. Jobs whose PID has died while status was `"running"` are marked `"abandoned"` in-place so subsequent calls skip them. The `_pid_alive()` function explicitly returns `False` for `pid <= 0`.

5. **No hard timeout and no no-progress timeout by default.** The `InvokerConfig` sets `inactivity_timeout=0` for async jobs, meaning the supervisor never kills Claude Code based on wall-clock or CPU-stall thresholds. The inactivity timeout feature (`CLAUDE_DELEGATE_INACTIVITY_TIMEOUT_SECONDS`) remains available as an explicit override for synchronous invocations where the caller wants a safety net, but async delegation intentionally omits it to preserve running work.

6. **Polling statuses are deterministic.** The polling endpoint returns one of: `running`, `completed`, `failed`, `not_found`, `lease_held`. These are derived from file state, not process state, so polling is reliable even if intermediate processes have exited.

## Risk: Runtime job files and cleanup

Each `--start` call creates a job directory under `.claude-delegate/runtime/jobs/<job_id>/` with `meta.json`, `config.json`, `stdout.txt`, `stderr.txt`, and `result.json`. These accumulate over time with no automatic cleanup. On a busy system with many delegations, disk usage grows linearly with job count.

**Mitigation:** Job directories are small (metadata, config, and tail output). The `--start` / `--poll` interface is designed for orchestrator-managed workflows where the orchestrator can clean up job directories after consuming results. A future enhancement could add a `--cleanup` flag or a GC policy based on job age, but this is deferred — the orchestrator is in the best position to know when results have been consumed.

## Risk: Orphaned supervisor processes

If the orchestrator crashes after `--start` returns but before polling completes, the detached supervisor continues running until Claude Code finishes and writes `result.json`. The job directory persists with a terminal result that is never consumed. The Claude Code process itself completes normally and exits — it is not orphaned in the "zombie" sense, only unmonitored.

**Mitigation:** Supervisor processes are short-lived relative to the system's lifetime (they exit when Claude Code exits). Orphaned job directories are small and follow the same accumulation profile as the general cleanup concern above. No SIGKILL rescue path is needed because the supervisor does not hold locks or shared resources.

## Risk: Determinism of polling

Polling reads files, which introduces a window between when the supervisor writes `result.json` and when the poller reads it. This could, in theory, return stale state. In practice, the write is atomic (short file, single `write_text` call) and the read follows it immediately. The race window is microseconds.

**Mitigation:** The `get_job_status()` function reads `result.json` first. If the file exists, it returns terminal state regardless of what `meta.json` says. This means a completed job is always reported as completed once `result.json` exists, even if `meta.json` still says `running`.

## Consequences

- Avoids token waste from premature reduced correction plans. Running jobs own exclusive execution until terminal completion or failure.
- Makes "running" an explicit lease state that other callers can observe and respect.
- Correction passes happen only after terminal completion/failure or explicit user cancellation — never speculatively.
- Adds runtime job files under `.claude-delegate/runtime/jobs/` with eventual cleanup as the main operational concern.
- Preserves backward compatibility with synchronous invocation. The `--start` / `--poll` path is additive; existing synchronous callers (no flags) are unaffected.
- Relies on deterministic polling and job persistence rather than in-memory process state, which makes the delegation outcome observable across process and session boundaries.
- Does not introduce a hard timeout or no-progress timeout as the default behavior for async jobs. The orchestrator decides when to stop waiting via polling, not a wall-clock deadline.
- The supervisor process records the real returncode of Claude Code. A non-zero exit is reported as `failed` with the actual returncode, not a synthetic "timeout" or "killed" status.

## Verification

The implementation is covered by wrapper-level tests in `bash tests/run_tests.sh`, including:

- Exit 0 triggers `completed` status with the parsed result output.
- Non-zero exit triggers `failed` status with the real returncode preserved.
- A sleeping job causes a second `--start` call to return `lease_held` with the original job's ID.
- `pid=0` is not treated as alive by `find_active_lease()`, preventing false lease detection during the window between `create_job_meta` and supervisor PID replacement.
- `find_active_lease()` returns `None` when no jobs exist, returns the active lease when a running job with an alive PID exists, and marks dead-PID jobs as `abandoned`.
- `poll_delegation_status` returns correct status for `running`, `completed`, `failed`, and `not_found` job states.
- The `--start` / `--poll` workflow is tested end-to-end through the wrapper, verifying that JSON output is parseable and contains the expected fields (`job_id`, `status`, `lease_active`, `pid`).
