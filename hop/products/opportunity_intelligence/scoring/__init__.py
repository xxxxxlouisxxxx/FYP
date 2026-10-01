"""Deterministic, decomposable hidden-opportunity score (spec 9.5). No model arithmetic."""

from __future__ import annotations

from collections.abc import Mapping

from hop.platform.analytics.stats import clamp
from hop.products.opportunity_intelligence.config import SCORE_COMPONENTS, ScoringRubric
from hop.products.opportunity_intelligence.contracts import RiskPenalty, ScoreBreakdown, ScoreComponent
from hop.products.opportunity_intelligence.gap_detection import MetricInput, compare, read_metric

FORMULA = (
    "0.30*demand_strength + 0.20*serp_supply_gap + 0.20*gerp_recommendation_gap + 0.15*strategic_relevance"
    " + 0.10*feasibility + 0.05*evidence_confidence - risk_penalties (weights from rubric)"
)


class MissingScoreInput(ValueError):
    pass


def score(
    components: Mapping[str, tuple[float | None, str, str]],
    metrics: Mapping[str, MetricInput],
    rubric: ScoringRubric,
) -> ScoreBreakdown:
    """``components`` maps component id -> (value in [0,1] or None, source, rationale).

    A missing component contributes nothing and is reported as missing; it is never scored as zero
    demand/gap. Callers must not admit candidates whose required components are missing.
    """
    parts: list[ScoreComponent] = []
    gross = 0.0
    for cid in SCORE_COMPONENTS:
        value, source, rationale = components.get(cid, (None, "missing", "not supplied"))
        weight = rubric.weights[cid]
        if value is not None:
            value = clamp(float(value))
        contribution = round(weight * value, 6) if value is not None else 0.0
        gross += contribution
        parts.append(
            ScoreComponent(
                component_id=cid,
                weight=weight,
                value=None if value is None else round(value, 6),
                contribution=contribution,
                source=source,
                rationale=rationale if value is not None else f"MISSING: {rationale}",
            )
        )
    penalties: list[RiskPenalty] = []
    total_penalty = 0.0
    for p in rubric.penalties:
        observed, state = read_metric(metrics, p.condition.metric, p.condition.field)
        if observed is None:
            applied = p.apply_when_missing
            reason = f"{p.condition.metric} is {state}; {'penalised conservatively' if applied else 'not penalised'}"
        else:
            applied = compare(p.condition.op, observed, p.condition.value)
            reason = f"{p.condition.metric}={observed:.3f} {p.condition.op} {p.condition.value}"
        if applied:
            total_penalty += p.amount
        penalties.append(
            RiskPenalty(
                penalty_id=p.penalty_id,
                label=p.label,
                amount=p.amount if applied else 0.0,
                applied=applied,
                observed=observed,
                reason=reason,
            )
        )
    total = round(clamp(gross - total_penalty), 6)
    thresholds = rubric.priority_thresholds
    priority = "HIGH" if total >= thresholds.high else "MEDIUM" if total >= thresholds.medium else "LOW"
    sensitivity = {
        p.component_id: round(0.05 * (p.value or 0.0) - 0.05 * _mean_other(parts, p.component_id), 6) for p in parts
    }
    return ScoreBreakdown(
        score_version=rubric.score_version,
        formula=FORMULA,
        components=parts,
        penalties=penalties,
        gross=round(gross, 6),
        total_penalty=round(total_penalty, 6),
        total=total,
        priority=priority,  # type: ignore[arg-type]
        sensitivity=sensitivity,
    )


def _mean_other(parts: list[ScoreComponent], exclude: str) -> float:
    """Sensitivity: +0.05 on one weight, re-normalised by taking 0.01 from each of the other five."""
    others = [p.value or 0.0 for p in parts if p.component_id != exclude]
    return sum(others) / len(others) if others else 0.0
