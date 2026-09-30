"""In-process durable workflow runtime.

Controls (spec 5.1): idempotent job keys, retries with backoff + jitter, per-activity and total-run
timeouts, maximum activity executions (loop guard), per-run budget, kill switch, cancellation,
resumable checkpoints, failure classification and a dead-letter table.

The ``Executor`` seam lets a Celery (or Temporal) worker call ``WorkflowRuntime.execute(run_id, ...)``
instead of the in-process executor without changing workflow definitions.
"""

from __future__ import annotations

import contextvars
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from sqlalchemy import select

from hop.platform.audit import AuditLog
from hop.platform.common_contracts import (
    ActorType,
    CollectionRun,
    CostEstimate,
    RunStatus,
    StepState,
    StepStatus,
    new_id,
    utcnow,
)
from hop.platform.observability import CostRecorder, Telemetry, current_trace_id
from hop.platform.policy_engine import KillSwitch
from hop.platform.storage.db import CheckpointRow, DeadLetterRow, RunRow, Store
from hop.platform.workflow_runtime.budget import BudgetLedger
from hop.platform.workflow_runtime.errors import (
    ActivityTimeout,
    BudgetExceeded,
    PermanentError,
    RunCancelled,
    TransientError,
    classify,
    is_retryable,
)
from hop.platform.workflow_runtime.retry import NO_RETRY, RetryOutcome, RetryPolicy, retry_call

__all__ = [
    "NO_RETRY",
    "Activity",
    "ActivityTimeout",
    "BudgetExceeded",
    "BudgetLedger",
    "InProcessExecutor",
    "PermanentError",
    "RetryOutcome",
    "RetryPolicy",
    "RunCancelled",
    "RunContext",
    "TransientError",
    "WorkflowDefinition",
    "WorkflowRuntime",
    "retry_call",
]

T = TypeVar("T")


@dataclass(frozen=True)
class Activity:
    name: str
    fn: Callable[[RunContext], dict[str, Any]]
    span_name: str
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    timeout_s: float | None = None


@dataclass(frozen=True)
class WorkflowDefinition:
    name: str
    version: str
    root_span_name: str
    activities: tuple[Activity, ...]


class Executor(Protocol):
    def submit(self, fn: Callable[[], T]) -> T: ...


class InProcessExecutor:
    def submit(self, fn: Callable[[], T]) -> T:
        return fn()


class RunContext:
    def __init__(
        self,
        *,
        run: CollectionRun,
        deps: Any,
        runtime: WorkflowRuntime,
        budget: BudgetLedger,
        deadline: float,
        attributes: dict[str, Any],
    ) -> None:
        self.run = run
        self.run_id = run.run_id
        self.request = run.request
        self.deps = deps
        self.runtime = runtime
        self.budget = budget
        self.deadline = deadline
        self.attributes = attributes
        self.state: dict[str, Any] = {}

    @property
    def trace_id(self) -> str | None:
        return current_trace_id()

    def span(self, name: str, attributes: dict[str, Any] | None = None) -> Any:
        return self.runtime.telemetry.span(name, {**self.attributes, **(attributes or {})})

    def check_controls(self) -> None:
        self.runtime.kill_switch.check()
        if time.monotonic() > self.deadline:
            raise ActivityTimeout("total run timeout exceeded")
        if self.runtime.status_of(self.run_id) == RunStatus.CANCELLED:
            raise RunCancelled("run cancelled by operator")

    def spend(
        self,
        amount_usd: float,
        *,
        category: str,
        provider: str,
        capability_id: str,
        units: float,
        unit: str,
        simulated: bool,
    ) -> None:
        self.budget.spend(amount_usd, f"{capability_id}:{unit}")
        self.runtime.costs.record(
            run_id=self.run_id,
            category=category,
            provider=provider,
            capability_id=capability_id,
            units=units,
            unit=unit,
            usd=amount_usd,
            simulated=simulated,
        )


class WorkflowRuntime:
    def __init__(
        self,
        *,
        store: Store,
        telemetry: Telemetry,
        kill_switch: KillSwitch,
        costs: CostRecorder,
        audit: AuditLog,
        tenant_id: str = "hktdc",
        run_timeout_s: float = 1800.0,
        max_activity_attempts: int = 60,
        executor: Executor | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.store = store
        self.telemetry = telemetry
        self.kill_switch = kill_switch
        self.costs = costs
        self.audit = audit
        self.tenant_id = tenant_id
        self.run_timeout_s = run_timeout_s
        self.max_activity_attempts = max_activity_attempts
        self.executor = executor or InProcessExecutor()
        self.sleep = sleep

    # persistence --------------------------------------------------------------------------
    def save(self, run: CollectionRun) -> None:
        with self.store.session() as s:
            s.merge(
                RunRow(
                    run_id=run.run_id,
                    idempotency_key=run.idempotency_key,
                    workflow=run.workflow,
                    status=run.status.value,
                    market=run.request.get("market"),
                    trace_id=run.trace_id,
                    created_at=run.created_at,
                    body=run.model_dump(mode="json"),
                )
            )

    def get(self, run_id: str) -> CollectionRun | None:
        with self.store.session() as s:
            row = s.get(RunRow, run_id)
            return CollectionRun.model_validate(row.body) if row else None

    def status_of(self, run_id: str) -> RunStatus | None:
        with self.store.session() as s:
            row = s.get(RunRow, run_id)
            return RunStatus(row.status) if row else None

    def find_by_key(self, key: str) -> CollectionRun | None:
        with self.store.session() as s:
            row = s.execute(select(RunRow).where(RunRow.idempotency_key == key)).scalar()
            return CollectionRun.model_validate(row.body) if row else None

    def list_runs(self, limit: int = 100) -> list[CollectionRun]:
        with self.store.session() as s:
            rows = s.execute(select(RunRow).order_by(RunRow.created_at.desc()).limit(limit)).scalars()
            return [CollectionRun.model_validate(r.body) for r in rows]

    def checkpoints(self, run_id: str) -> dict[str, dict[str, Any]]:
        with self.store.session() as s:
            rows = s.execute(select(CheckpointRow).where(CheckpointRow.run_id == run_id)).scalars()
            return {r.step: r.output for r in rows if r.status == StepStatus.SUCCEEDED.value}

    def dead_letters(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.store.session() as s:
            rows = s.execute(select(DeadLetterRow).order_by(DeadLetterRow.created_at.desc()).limit(limit)).scalars()
            return [
                {
                    "run_id": r.run_id,
                    "step": r.step,
                    "failure_class": r.failure_class,
                    "error": r.error,
                    "payload": r.payload,
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ]

    # lifecycle ----------------------------------------------------------------------------
    def start(
        self,
        workflow: WorkflowDefinition,
        *,
        idempotency_key: str,
        request: dict[str, Any],
        budget_usd: float,
        deps: Any,
        attributes: dict[str, Any] | None = None,
        cost_estimate: CostEstimate | None = None,
        force_new: bool = False,
    ) -> CollectionRun:
        key = f"{workflow.name}:{idempotency_key}"
        if force_new:
            key = f"{key}:{new_id('n')}"
        existing = self.find_by_key(key)
        if existing is not None:
            return existing
        run = CollectionRun(
            run_id=new_id("run"),
            idempotency_key=key,
            workflow=workflow.name,
            workflow_version=workflow.version,
            status=RunStatus.PENDING,
            tenant_id=self.tenant_id,
            request=request,
            cost_estimate=cost_estimate,
            budget_usd=budget_usd,
            steps=[StepState(name=a.name) for a in workflow.activities],
        )
        self.save(run)
        return self.executor.submit(lambda: self.execute(run.run_id, workflow, deps, attributes or {}))

    def resume(
        self, run_id: str, workflow: WorkflowDefinition, deps: Any, attributes: dict[str, Any] | None = None
    ) -> CollectionRun:
        run = self.get(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.status == RunStatus.SUCCEEDED:
            return run
        run.resumed_count += 1
        run.status = RunStatus.PENDING
        self.save(run)
        return self.executor.submit(lambda: self.execute(run_id, workflow, deps, attributes or {}))

    def cancel(self, run_id: str, actor: str) -> None:
        run = self.get(run_id)
        if run is None:
            raise KeyError(run_id)
        run.status = RunStatus.CANCELLED
        self.save(run)
        self.audit.record(
            actor=actor, actor_type=ActorType.HUMAN, action="run.cancel", resource_type="run", resource_id=run_id
        )

    def execute(
        self, run_id: str, workflow: WorkflowDefinition, deps: Any, attributes: dict[str, Any]
    ) -> CollectionRun:
        run = self.get(run_id)
        if run is None:
            raise KeyError(run_id)
        done = self.checkpoints(run_id)
        steps = {s.name: s for s in run.steps}
        budget = BudgetLedger(limit_usd=run.budget_usd, spent_usd=self.costs.total_for_run(run_id))
        attrs = {
            "run.id": run_id,
            "workflow.name": workflow.name,
            "workflow.version": workflow.version,
            **attributes,
        }
        with self.telemetry.span(workflow.root_span_name, {**attrs, "run.resumed_count": run.resumed_count}) as root:
            if run.trace_id and run.trace_id != current_trace_id():
                run.summary.setdefault("previous_trace_ids", []).append(run.trace_id)
            run.trace_id = current_trace_id()
            run.status = RunStatus.RUNNING
            run.started_at = run.started_at or utcnow()
            self.save(run)
            ctx = RunContext(
                run=run,
                deps=deps,
                runtime=self,
                budget=budget,
                deadline=time.monotonic() + self.run_timeout_s,
                attributes=attrs,
            )
            total_attempts = 0
            for activity in workflow.activities:
                state = steps.setdefault(activity.name, StepState(name=activity.name))
                if activity.name in done:
                    state.status = StepStatus.SUCCEEDED
                    state.restored_from_checkpoint = True
                    state.summary = done[activity.name]
                    continue
                try:
                    ctx.check_controls()
                    outcome = RetryOutcome()
                    state.status = StepStatus.RUNNING
                    state.started_at = utcnow()
                    self._sync_steps(run, steps)
                    t0 = time.perf_counter()

                    def attempt(activity: Activity = activity, state: StepState = state) -> dict[str, Any]:
                        nonlocal total_attempts
                        total_attempts += 1
                        state.attempts += 1
                        if total_attempts > self.max_activity_attempts:
                            raise PermanentError("maximum activity executions per run exceeded (loop guard)")
                        ctx.check_controls()
                        with ctx.span(
                            activity.span_name, {"activity.name": activity.name, "activity.attempt": state.attempts}
                        ):
                            return self._run_with_timeout(activity, ctx)

                    summary = retry_call(attempt, activity.retry, sleep=self.sleep, outcome=outcome)
                    state.status = StepStatus.SUCCEEDED
                    state.summary = summary or {}
                    state.finished_at = utcnow()
                    state.duration_ms = round((time.perf_counter() - t0) * 1000, 2)
                    state.error = None
                    state.failure_class = None
                    self._checkpoint(run_id, activity.name, state.summary)
                    self._sync_steps(run, steps)
                except Exception as exc:  # classified below; nothing is swallowed silently
                    failure = classify(exc)
                    state.status = StepStatus.FAILED
                    state.error = f"{type(exc).__name__}: {exc}"[:2000]
                    state.failure_class = failure
                    state.finished_at = utcnow()
                    run.error = state.error
                    run.failure_class = failure
                    run.status = {
                        "kill_switch": RunStatus.KILLED,
                        "cancelled": RunStatus.CANCELLED,
                        "budget_exceeded": RunStatus.REJECTED_BUDGET,
                    }.get(failure, RunStatus.FAILED)
                    root.set_attribute("run.failure_class", failure)
                    self._dead_letter(run_id, activity.name, failure, state.error, ctx)
                    self._finish(run, steps)
                    return run
            run.status = RunStatus.SUCCEEDED
            run.error = None
            run.failure_class = None
            self._finish(run, steps)
            root.set_attribute("run.cost_usd", run.actual_cost_usd)
            return run

    # helpers ------------------------------------------------------------------------------
    def _run_with_timeout(self, activity: Activity, ctx: RunContext) -> dict[str, Any]:
        if activity.timeout_s is None:
            return activity.fn(ctx)
        context = contextvars.copy_context()
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"act-{activity.name}")
        future = pool.submit(context.run, activity.fn, ctx)
        try:
            return future.result(timeout=activity.timeout_s)
        except FutureTimeout as exc:
            raise ActivityTimeout(f"activity {activity.name} exceeded {activity.timeout_s}s") from exc
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _sync_steps(self, run: CollectionRun, steps: dict[str, StepState]) -> None:
        run.steps = list(steps.values())
        if self.status_of(run.run_id) == RunStatus.CANCELLED:
            return
        self.save(run)

    def _checkpoint(self, run_id: str, step: str, output: dict[str, Any]) -> None:
        with self.store.session() as s:
            existing = s.execute(
                select(CheckpointRow).where(CheckpointRow.run_id == run_id, CheckpointRow.step == step)
            ).scalar()
            if existing is None:
                s.add(CheckpointRow(run_id=run_id, step=step, status=StepStatus.SUCCEEDED.value, output=output))
            else:
                existing.status = StepStatus.SUCCEEDED.value
                existing.output = output

    def _dead_letter(self, run_id: str, step: str, failure: str, error: str, ctx: RunContext) -> None:
        with self.store.session() as s:
            s.add(
                DeadLetterRow(
                    run_id=run_id,
                    step=step,
                    failure_class=failure,
                    error=error,
                    payload={
                        "request": ctx.request,
                        "trace_id": current_trace_id(),
                        "retryable": failure == "transient",
                    },
                )
            )
        self.audit.record(
            actor="workflow_runtime",
            actor_type=ActorType.SYSTEM,
            action="run.step_failed",
            resource_type="run",
            resource_id=run_id,
            outcome="FAILURE",
            details={"step": step, "failure_class": failure},
            trace_id=current_trace_id(),
        )

    def _finish(self, run: CollectionRun, steps: dict[str, StepState]) -> None:
        run.steps = list(steps.values())
        run.finished_at = utcnow()
        run.actual_cost_usd = round(self.costs.total_for_run(run.run_id), 6)
        self.save(run)
        self.audit.record(
            actor="workflow_runtime",
            actor_type=ActorType.SYSTEM,
            action=f"run.{run.status.value.lower()}",
            resource_type="run",
            resource_id=run.run_id,
            outcome="SUCCESS" if run.status == RunStatus.SUCCEEDED else "FAILURE",
            details={"cost_usd": run.actual_cost_usd, "failure_class": run.failure_class},
            trace_id=run.trace_id,
        )


def is_transient(exc: BaseException) -> bool:
    return is_retryable(exc)
