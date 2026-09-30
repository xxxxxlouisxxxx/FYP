"""Deterministic, versioned gap-rule evaluation with three-valued logic.

A condition over a missing metric is UNKNOWN (never treated as zero), and a rule only matches when
every condition is TRUE. Rules cannot be changed at runtime; they come from the validated domain pack.
"""

from __future__ import annotations

import operator
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from hop.platform.common_contracts import MeasuredValue, Proportion, metric_field
from hop.products.opportunity_intelligence.config import Condition, GapRule, GapRuleSet

_OPS = {">=": operator.ge, "<=": operator.le, ">": operator.gt, "<": operator.lt}

MetricInput = MeasuredValue | Proportion | float | int | None


def read_metric(metrics: Mapping[str, MetricInput], name: str, field_name: str = "value") -> tuple[float | None, str]:
    value = metrics.get(name)
    if value is None:
        return None, "NOT_COLLECTED"
    if isinstance(value, int | float):
        return float(value), "OBSERVED_VALUE"
    if isinstance(value, Proportion) and field_name == "value":
        field_name = "rate"
    return metric_field(value, field_name), value.state.value


def compare(op: str, observed: float, threshold: float) -> bool:
    if op == "==":
        return abs(observed - threshold) <= 1e-9
    if op == "!=":
        return abs(observed - threshold) > 1e-9
    return bool(_OPS[op](observed, threshold))


@dataclass
class ConditionResult:
    metric: str
    field: str
    op: str
    threshold: float
    observed: float | None
    state: str
    outcome: str  # TRUE | FALSE | UNKNOWN

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class RuleEvaluation:
    rule: GapRule
    conditions: list[ConditionResult] = field(default_factory=list)

    @property
    def matched(self) -> bool:
        return all(c.outcome == "TRUE" for c in self.conditions)

    @property
    def unknown(self) -> bool:
        return (
            not self.matched
            and any(c.outcome == "UNKNOWN" for c in self.conditions)
            and not any(c.outcome == "FALSE" for c in self.conditions)
        )


def evaluate_condition(cond: Condition, metrics: Mapping[str, MetricInput]) -> ConditionResult:
    observed, state = read_metric(metrics, cond.metric, cond.field)
    outcome = "UNKNOWN" if observed is None else "TRUE" if compare(cond.op, observed, cond.value) else "FALSE"
    return ConditionResult(cond.metric, cond.field, cond.op, cond.value, observed, state, outcome)


def evaluate_rule(rule: GapRule, metrics: Mapping[str, MetricInput]) -> RuleEvaluation:
    return RuleEvaluation(rule, [evaluate_condition(c, metrics) for c in rule.all_of])


@dataclass
class RuleTestReport:
    rule_set_id: str
    version: str
    results: list[dict[str, Any]]

    @property
    def passed(self) -> bool:
        return all(r["passed"] for r in self.results)


def run_rule_tests(rule_set: GapRuleSet) -> RuleTestReport:
    results = []
    for rule in rule_set.rules:
        if not rule.tests:
            results.append(
                {"rule_id": rule.rule_id, "test": "(no tests)", "passed": False, "detail": "rule has no tests"}
            )
        for test in rule.tests:
            ev = evaluate_rule(rule, test.metrics)
            results.append(
                {
                    "rule_id": rule.rule_id,
                    "test": test.name,
                    "expected": test.expected,
                    "actual": ev.matched,
                    "passed": ev.matched == test.expected,
                    "detail": ", ".join(f"{c.metric}{c.op}{c.threshold}->{c.outcome}" for c in ev.conditions),
                }
            )
    return RuleTestReport(rule_set.rule_set_id, rule_set.version, results)
