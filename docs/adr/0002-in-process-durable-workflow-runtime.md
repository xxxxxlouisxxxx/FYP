# ADR 0002: In-process, checkpointed workflow runtime before Temporal or Celery

- Status: Accepted for the walking skeleton; revisit at Phase 5
- Date: 2026-09-30
- Spec: 5.1, 17, 22 (P2 "migration to a more durable workflow engine if operational evidence supports it")

## Context

Spec 5.1 needs idempotent runs, retries with backoff, activity timeouts, run and step budgets, a
global kill switch, checkpoints, resumability and dead letters. The plan also warns against building
a complex orchestration layer before real products show the need (section 22).

## Decision

`hop.platform.workflow_runtime.WorkflowRuntime` runs a `WorkflowDefinition`, which is an ordered list
of `Activity(name, fn, span_name, retry, timeout_s)`, through an `Executor` protocol. The only executor
today is `InProcessExecutor`.

- **Idempotency:** `workflow:sha256(canonical request)` identifies a run. The same request in the same
  collection window returns the existing run. `--force-new` / `force_new=True` opts out.
- **Checkpoints:** each successful activity writes its output to `checkpoints`. A resumed run skips
  checkpointed activities and marks them `restored_from_checkpoint`. Later activities read earlier
  outputs from checkpoints (`step_output`), never from process memory.
- **Failure classes:** failures are classified as `transient`, `timeout`, `permanent`,
  `budget_exceeded`, `kill_switch`, `policy_violation`, `cancelled`, `validation` or `unexpected`.
  Transient failures and timeouts are retried with jittered exponential backoff. A failure that is not
  retried, or that exhausts its retries, writes a dead letter and a hash-chained audit event. The
  failure class sets the run status: `KILLED`, `REJECTED_BUDGET`, `CANCELLED` or `FAILED`.
- **Limits:** a per-run budget ledger is checked before every provider and model spend. The runtime
  also enforces per-activity timeouts, a run deadline and a loop guard on total activity executions.
- **Kill switch:** it is checked before every activity attempt, provider request and model call. It
  can be set through the environment (`HOP_KILL_SWITCH=1`) or the CLI (`hop runtime kill-switch on`).

## Consequences

- There are no extra services to run, and every guarantee above is covered by tests
  (`tests/e2e/test_discovery_pipeline.py`).
- Runs execute synchronously in the caller's process (the CLI or an API request). This is acceptable for
  sandbox and tier-A runs, which take a few seconds. Long real-provider runs need a worker.
- **Migration path:** implement `Executor.submit` for Celery (Redis is already in
  `infrastructure/docker-compose.yml`) or Temporal. Activities are already pure functions of
  `(RunContext) -> dict`, and their state is persisted, so they map directly to Temporal activities.
