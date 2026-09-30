"""Generic evaluation harness (spec 10): run an evaluator over a versioned golden set, compare the result
with a quality ratchet and the current champion, and persist a pass/fail EvaluationRun.

Evaluators are supplied by products; the harness knows nothing about the task being evaluated.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from hop.platform.audit import AuditLog
from hop.platform.common_contracts import ActorType, EvaluationRun, utcnow
from hop.platform.observability import Telemetry, current_trace_id
from hop.platform.storage.db import EvaluationRunRow, Store


@dataclass
class EvaluatorOutput:
    metrics: dict[str, float | None]
    n_cases: int
    subject: dict[str, str]
    failures: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class RatchetSpec:
    primary_metric: str
    minimum: float
    maximum_regression: float
    secondary_metrics: dict[str, float] = field(default_factory=dict)


Evaluator = Callable[[dict[str, Any]], EvaluatorOutput]


def ratchet_checks(
    metrics: dict[str, float | None], ratchet: RatchetSpec, champion: dict[str, Any] | None
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def add(name: str, metric: str, observed: float | None, op: str, threshold: float) -> None:
        passed = observed is not None and (
            observed >= threshold - 1e-12 if op == ">=" else observed <= threshold + 1e-12
        )
        checks.append(
            {
                "check": name,
                "metric": metric,
                "observed": observed,
                "op": op,
                "threshold": round(threshold, 6),
                "passed": passed,
            }
        )

    primary = metrics.get(ratchet.primary_metric)
    add("primary_minimum", ratchet.primary_metric, primary, ">=", ratchet.minimum)
    if champion and champion.get(ratchet.primary_metric) is not None:
        add(
            "no_regression_vs_champion",
            ratchet.primary_metric,
            primary,
            ">=",
            float(champion[ratchet.primary_metric]) - ratchet.maximum_regression,
        )
    for metric, threshold in ratchet.secondary_metrics.items():
        add("secondary_minimum", metric, metrics.get(metric), ">=", threshold)
    return checks


class EvaluationHarness:
    def __init__(self, store: Store, telemetry: Telemetry, audit: AuditLog) -> None:
        self.store = store
        self.telemetry = telemetry
        self.audit = audit

    def run(
        self,
        *,
        suite_id: str,
        suite_version: str,
        partition: str,
        dataset: dict[str, Any],
        evaluator: Evaluator,
        ratchet: RatchetSpec,
        champion: dict[str, Any] | None = None,
        actor: str = "evaluation_harness",
    ) -> EvaluationRun:
        started = utcnow()
        with self.telemetry.span(
            "Evaluation", {"evaluation.suite": suite_id, "evaluation.partition": partition}
        ) as span:
            out = evaluator(dataset)
            checks = ratchet_checks(out.metrics, ratchet, champion)
            passed = all(c["passed"] for c in checks)
            span.set_attribute("evaluation.passed", passed)
            result = EvaluationRun(
                suite_id=suite_id,
                suite_version=suite_version,
                dataset_version=str(dataset.get("version", "unknown")),
                partition=partition,
                subject=out.subject,
                metrics={k: (round(v, 6) if v is not None else None) for k, v in out.metrics.items()},
                thresholds={
                    "primary": {ratchet.primary_metric: ratchet.minimum},
                    "secondary": dict(ratchet.secondary_metrics),
                    "champion": {k: v for k, v in (champion or {}).items() if isinstance(v, int | float)},
                },
                checks=checks,
                passed=passed,
                n_cases=out.n_cases,
                failures=out.failures[:100],
                started_at=started,
                finished_at=utcnow(),
                trace_id=current_trace_id(),
            )
        with self.store.session() as s:
            s.add(
                EvaluationRunRow(
                    evaluation_run_id=result.evaluation_run_id,
                    suite_id=suite_id,
                    passed=int(passed),
                    body=result.model_dump(mode="json"),
                )
            )
        self.audit.record(
            actor=actor,
            actor_type=ActorType.SYSTEM,
            action="evaluation.run",
            resource_type="evaluation_suite",
            resource_id=suite_id,
            outcome="SUCCESS" if passed else "FAILURE",
            details={"evaluation_run_id": result.evaluation_run_id, "metrics": result.metrics},
            trace_id=result.trace_id,
        )
        return result

    def history(self, suite_id: str | None = None, limit: int = 50) -> list[EvaluationRun]:
        with self.store.session() as s:
            q = select(EvaluationRunRow).order_by(EvaluationRunRow.created_at.desc()).limit(limit)
            if suite_id:
                q = q.where(EvaluationRunRow.suite_id == suite_id)
            return [EvaluationRun.model_validate(r.body) for r in s.execute(q).scalars()]
