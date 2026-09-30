"""Scoring activity: derive the six rubric components from metrics and score each candidate."""

from __future__ import annotations

from typing import Any

from hop.platform.common_contracts import MeasuredValue, Proportion
from hop.platform.workflow_runtime import RunContext
from hop.products.opportunity_intelligence.contracts import AdmissionOutcome, GapCandidate
from hop.products.opportunity_intelligence.deps import DiscoveryDeps
from hop.products.opportunity_intelligence.scoring import score

Component = tuple[float | None, str, str]


def _v(metrics: dict[str, Any], name: str) -> float | None:
    m = metrics.get(name)
    if m is None or not m.is_observed:
        return None
    return m.rate if isinstance(m, Proportion) else m.value


def evidence_confidence(c: GapCandidate) -> float:
    fam_cov = len(c.observed_signal_families) / 3
    min_n = _v(c.metrics, "quality.min_sample_n")
    sample = min(1.0, (min_n or 0) / 30)
    amb = c.entity_ambiguity_rate or 0.0
    return round(0.4 * fam_cov + 0.3 * sample + 0.3 * (1 - amb), 4)


def components_for(c: GapCandidate) -> dict[str, Component]:
    m = c.metrics
    demand = _v(m, "demand.index")
    supply = _v(m, "serp.supply_share")
    if c.brand_id:
        rec = _v(m, "gerp.brand_recommendation_rate")
        rec_src = "1 - gerp.brand_recommendation_rate"
    else:
        rec = _v(m, "gerp.recommendation_coverage")
        rec_src = "1 - gerp.recommendation_coverage"
    return {
        "demand_strength": (demand, "demand.index", "log-scaled monthly search volume vs market reference"),
        "serp_supply_gap": (
            None if supply is None else 1 - supply,
            "1 - serp.supply_share",
            "share of top-10 results that are not on-need product supply",
        ),
        "gerp_recommendation_gap": (
            None if rec is None else 1 - rec,
            rec_src,
            "share of generative answers without a concrete recommendation",
        ),
        "strategic_relevance": (_v(m, "need.strategic_relevance"), "domain pack taxonomy", "HKTDC strategic relevance"),
        "feasibility": (_v(m, "need.feasibility"), "domain pack taxonomy", "supplier feasibility rating"),
        "evidence_confidence": (
            evidence_confidence(c),
            "derived",
            "0.4*family coverage + 0.3*min(1, n/30) + 0.3*(1 - entity ambiguity)",
        ),
    }


def score_candidates(ctx: RunContext) -> dict[str, Any]:
    deps: DiscoveryDeps = ctx.deps
    repo, rubric = deps.repo, deps.config.scoring
    deps.platform.policy.enforce_capability("opportunity.scoring", ctx.run_id)
    by_priority: dict[str, int] = {}
    scored = 0
    for c in repo.candidates(ctx.run_id):
        if c.admission in (AdmissionOutcome.QUARANTINED, AdmissionOutcome.REJECTED):
            continue
        metrics = dict(c.metrics)
        metrics.setdefault("counter.strength", MeasuredValue.missing("NOT_COLLECTED", "counter-evidence not run"))  # type: ignore[arg-type]
        breakdown = score(components_for(c), metrics, rubric)
        c.score = breakdown
        c.score_version = rubric.score_version
        repo.upsert_candidate(c)
        scored += 1
        if c.admission == AdmissionOutcome.ADMITTED:
            by_priority[breakdown.priority] = by_priority.get(breakdown.priority, 0) + 1
    return {"scored": scored, "admitted_by_priority": by_priority, "score_version": rubric.score_version}
