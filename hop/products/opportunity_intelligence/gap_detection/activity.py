"""Gap-detection workflow activity: evaluate the active rule set and create Gap Candidates."""

from __future__ import annotations

from typing import Any

from hop.platform.common_contracts import EvidenceItem, EvidenceType, SignalFamily, ValueState, stable_id
from hop.platform.policy_engine.tools import AgentSession
from hop.platform.workflow_runtime import RunContext
from hop.products.opportunity_intelligence.config import GapRule
from hop.products.opportunity_intelligence.contracts import GapCandidate
from hop.products.opportunity_intelligence.deps import DiscoveryDeps, step_output
from hop.products.opportunity_intelligence.gap_detection import evaluate_rule
from hop.products.opportunity_intelligence.metrics import load_metrics

FAMILY_PROBE = {
    SignalFamily.DEMAND: "demand.index",
    SignalFamily.SERP: "serp.supply_share",
    SignalFamily.GERP: "gerp.answers",
}
MAX_SUPPORT_PER_FAMILY = 8


def observed_families(metrics: dict[str, Any]) -> list[SignalFamily]:
    out = []
    for fam, probe in FAMILY_PROBE.items():
        m = metrics.get(probe)
        if m is not None and m.is_observed:
            out.append(fam)
    return out


def _support(
    session: AgentSession, run_id: str, rule: GapRule, need_id: str, brand_id: str | None
) -> list[EvidenceItem]:
    chosen: list[EvidenceItem] = []
    fams = set(rule.signal_families)
    if SignalFamily.DEMAND in fams:
        chosen += session.call(
            "evidence.search", run_id=run_id, need_id=need_id, evidence_types=[EvidenceType.DEMAND_SIGNAL]
        )[:MAX_SUPPORT_PER_FAMILY]
    if SignalFamily.SERP in fams:
        serp = session.call(
            "evidence.search", run_id=run_id, need_id=need_id, evidence_types=[EvidenceType.SERP_RESULT]
        )
        if brand_id:
            serp = [e for e in serp if brand_id in e.entity_refs]
        elif rule.gap_family == "NO_DOMINANT_SUPPLYING_BRAND":
            serp = [e for e in serp if e.entity_refs]
        else:
            serp = [e for e in serp if not e.attributes.get("supply")]
        chosen += sorted(serp, key=lambda e: e.attributes.get("rank", 99))[:MAX_SUPPORT_PER_FAMILY]
    if SignalFamily.GERP in fams:
        if rule.gap_family == "GERP_RECOMMENDATION_WEAK_SEARCH_SUPPORT":
            chosen += session.call(
                "evidence.search", run_id=run_id, need_id=need_id, evidence_types=[EvidenceType.GERP_CITATION]
            )[:MAX_SUPPORT_PER_FAMILY]
        else:
            answers = session.call(
                "evidence.search", run_id=run_id, need_id=need_id, evidence_types=[EvidenceType.GERP_ANSWER]
            )
            if brand_id:
                answers = [
                    a
                    for a in answers
                    if a.attributes.get("brand_labels", {}).get(brand_id)
                    not in ("PRIMARY_RECOMMENDATION", "SUPPORTING_RECOMMENDATION")
                ]
            elif rule.gap_family == "HIGH_DEMAND_WEAK_GERP_COVERAGE":
                answers = [a for a in answers if not a.attributes.get("has_recommendation")]
            chosen += answers[:MAX_SUPPORT_PER_FAMILY]
    return chosen


def detect_gaps(ctx: RunContext) -> dict[str, Any]:
    deps: DiscoveryDeps = ctx.deps
    pack, repo, cfg = deps.pack, deps.repo, deps.config
    rule_set = cfg.active_rule_set
    market = pack.market(ctx.request["market"])
    dq = step_output(ctx, "data_quality").get("needs", {})
    records = repo.metrics(ctx.run_id)
    need_metrics = {r["need_id"]: load_metrics(r) for r in records if r["scope"] == "need"}
    brand_records = [r for r in records if r["scope"] == "brand"]
    session = AgentSession(
        policy=deps.platform.policy,
        tools=deps.tools,
        telemetry=deps.platform.telemetry,
        capability_id="opportunity.evidence_retrieval",
        run_id=ctx.run_id,
    )
    deps.platform.policy.enforce_capability("opportunity.gap_detection", ctx.run_id)
    repo.delete_candidates(ctx.run_id)
    evaluations: list[dict[str, Any]] = []
    created = 0
    for rule in (r for r in rule_set.rules if r.enabled):
        scopes: list[tuple[str, str | None, dict[str, Any]]] = []
        if rule.scope == "need":
            scopes = [(n, None, m) for n, m in sorted(need_metrics.items())]
        else:
            for r in brand_records:
                merged = {**need_metrics.get(r["need_id"], {}), **load_metrics(r)}
                scopes.append((r["need_id"], r["brand_id"], merged))
        for need_id, brand_id, metrics in scopes:
            ev = evaluate_rule(rule, metrics)
            outcome = "MATCHED" if ev.matched else "UNKNOWN" if ev.unknown else "NOT_MATCHED"
            evaluations.append(
                {
                    "rule_id": rule.rule_id,
                    "need_id": need_id,
                    "brand_id": brand_id,
                    "outcome": outcome,
                    "conditions": [c.as_dict() for c in ev.conditions],
                }
            )
            if not ev.matched:
                continue
            with ctx.span("Evidence retrieval", {"rule.id": rule.rule_id, "need.id": need_id}):
                support = _support(session, ctx.run_id, rule, need_id, brand_id)
                session.steps = 0
            need = pack.needs[need_id]
            amb = metrics.get("quality.entity_ambiguity_rate")
            fresh = metrics.get("quality.freshness_days")
            candidate = GapCandidate(
                candidate_id=stable_id("gap", ctx.run_id, rule.rule_id, need_id, brand_id or "-"),
                run_id=ctx.run_id,
                trace_id=ctx.trace_id,
                domain_pack=pack.pack_id,
                domain_pack_version=pack.version,
                rule_set_id=rule_set.rule_set_id,
                rule_id=rule.rule_id,
                rule_version=rule.version,
                gap_family=rule.gap_family,
                market=market.code,
                need_id=need_id,
                need_label=need.label.get("en", need_id),
                brand_id=brand_id,
                attribute_ids=list(need.attributes),
                signal_families=list(rule.signal_families),
                observed_signal_families=[f for f in observed_families(metrics) if f in rule.signal_families],
                metrics=metrics,
                condition_trace=[c.as_dict() for c in ev.conditions],
                supporting_evidence_ids=[e.evidence_id for e in support],
                entity_ambiguity_rate=amb.value if amb is not None and amb.is_observed else None,
                freshness_days=fresh.value if fresh is not None and fresh.is_observed else None,
                freshness_policy_days=market.freshness_policy_days,
                data_quality_status=dq.get(need_id, {}).get("status", "PASSED"),
            )
            repo.upsert_candidate(candidate)
            created += 1
    counts: dict[str, int] = {}
    for e in evaluations:
        counts[e["outcome"]] = counts.get(e["outcome"], 0) + 1
    return {
        "rule_set": f"{rule_set.rule_set_id}@{rule_set.version}",
        "candidates": created,
        "evaluations": counts,
        "matrix": evaluations,
    }


def missing_state(metric: Any) -> str:
    return metric.state.value if metric is not None else ValueState.NOT_COLLECTED.value
