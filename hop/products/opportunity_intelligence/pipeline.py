"""The Opportunity Discovery workflow (spec 7): an ordered list of durable, checkpointed activities."""

from __future__ import annotations

from typing import Any

from hop.platform.common_contracts import CollectionRequest, CollectionRun, CostEstimate, RunStatus
from hop.platform.workflow_runtime import (
    NO_RETRY,
    Activity,
    BudgetExceeded,
    PermanentError,
    RetryPolicy,
    RunContext,
    WorkflowDefinition,
)
from hop.products.opportunity_intelligence.collection import (
    budget_for,
    collect_demand,
    collect_gerp,
    collect_serp,
    estimate_cost,
    repeats_for,
)
from hop.products.opportunity_intelligence.counter_evidence import counter_evidence
from hop.products.opportunity_intelligence.deps import DiscoveryDeps
from hop.products.opportunity_intelligence.gap_detection import run_rule_tests
from hop.products.opportunity_intelligence.gap_detection.activity import detect_gaps
from hop.products.opportunity_intelligence.gap_detection.admission import admission_gates
from hop.products.opportunity_intelligence.metrics import compute_metrics
from hop.products.opportunity_intelligence.normalisation import data_quality, normalise, resolve_entities
from hop.products.opportunity_intelligence.opportunity_lifecycle.cards import create_cards
from hop.products.opportunity_intelligence.scoring.activity import score_candidates

WORKFLOW_NAME = "opportunity_discovery"
WORKFLOW_VERSION = "1.0.0"


def _estimate(deps: DiscoveryDeps, req: CollectionRequest, run_id: str = "estimate") -> CostEstimate:
    gateway = deps.platform.gateway
    spec = gateway.models[gateway.default_model]
    serp, demand = deps.serp_provider(run_id), deps.demand_provider(run_id)
    return estimate_cost(
        deps.pack,
        req,
        serp_unit=serp.unit_cost_usd,
        demand_unit=demand.unit_cost_usd,
        model_pricing=(spec.cost_per_1k_input_usd, spec.cost_per_1k_output_usd),
        simulated=deps.provider_mode == "sandbox" and spec.simulated,
    )


def validate_config(ctx: RunContext) -> dict[str, Any]:
    deps: DiscoveryDeps = ctx.deps
    req = CollectionRequest.model_validate(ctx.request)
    pack, policy = deps.pack, deps.platform.policy
    if req.domain_pack != pack.pack_id:
        raise PermanentError(f"request targets pack {req.domain_pack} but {pack.pack_id} is loaded")
    try:
        market = pack.market(req.market)
        queries = pack.queries_for(req.market, req.tier, req.language)
    except KeyError as exc:
        raise PermanentError(str(exc)) from exc
    if not market.enabled:
        raise PermanentError(f"market {req.market} is disabled in the domain pack")
    if not queries:
        raise PermanentError(f"no queries configured for {req.market} tier {req.tier}")
    report = run_rule_tests(deps.config.active_rule_set)
    if not report.passed:
        raise PermanentError(f"gap rule tests failing for {report.rule_set_id}; refusing to run")
    capabilities = [
        deps.serp_provider(ctx.run_id).capability_id,
        deps.demand_provider(ctx.run_id).capability_id,
        "gerp.observe",
        "gerp.extract",
        "opportunity.gap_detection",
        "opportunity.counter_evidence",
        "opportunity.scoring",
        "opportunity.explanation",
    ]
    for cap in capabilities:
        policy.enforce_capability(cap, ctx.run_id)
    return {
        "domain_pack": f"{pack.pack_id}@{pack.version}",
        "pack_hash": pack.content_hash[:16],
        "market": req.market,
        "tier": req.tier,
        "queries": len(queries),
        "needs": len({q.need_id for q in queries}),
        "languages": sorted({q.language for q in queries}),
        "gerp_repeats": repeats_for(pack, req),
        "provider_mode": deps.provider_mode,
        "rule_set": f"{report.rule_set_id}@{report.version}",
        "rule_tests_passed": len(report.results),
        "capabilities_checked": capabilities,
    }


def check_budget(ctx: RunContext) -> dict[str, Any]:
    deps: DiscoveryDeps = ctx.deps
    req = CollectionRequest.model_validate(ctx.request)
    estimate = _estimate(deps, req, ctx.run_id)
    if not estimate.within_budget:
        raise BudgetExceeded(f"estimated ${estimate.total_usd:.4f} exceeds budget ${estimate.budget_usd:.2f}")
    return {
        "estimate_usd": estimate.total_usd,
        "budget_usd": estimate.budget_usd,
        "lines": [line.model_dump() for line in estimate.lines],
    }


def run_evaluation(ctx: RunContext) -> dict[str, Any]:
    """Run-level release checks: card evidence exists, no quarantined support, explanations validated, audit intact."""
    deps: DiscoveryDeps = ctx.deps
    evidence = deps.platform.evidence
    problems: list[str] = []
    cards = deps.repo.cards(run_id=ctx.run_id)
    for card in cards:
        for eid in card.supporting_evidence_ids:
            item = evidence.get(eid)
            if item is None:
                problems.append(f"{card.card_id}: unknown evidence {eid}")
            elif item.data_quality_status.value == "QUARANTINED":
                problems.append(f"{card.card_id}: quarantined evidence {eid} used as support")
        if not card.explanation.validated:
            problems.append(f"{card.card_id}: explanation not validated")
    chain_ok, events = deps.platform.audit.verify_chain()
    if not chain_ok:
        problems.append("audit hash chain broken")
    if problems:
        raise PermanentError("; ".join(problems[:5]))
    return {"cards_checked": len(cards), "audit_chain_valid": chain_ok, "audit_events": events, "unsupported_claims": 0}


def build_workflow(activity_timeout_s: float = 120.0) -> WorkflowDefinition:
    provider_retry = RetryPolicy(max_attempts=2, base_delay_s=0.2, max_delay_s=2.0)
    t = activity_timeout_s
    return WorkflowDefinition(
        name=WORKFLOW_NAME,
        version=WORKFLOW_VERSION,
        root_span_name="Opportunity Discovery Run",
        activities=(
            Activity("validate_config", validate_config, "Configuration validation", NO_RETRY),
            Activity("estimate_cost", check_budget, "Cost estimation", NO_RETRY),
            Activity("collect_demand", collect_demand, "Query collection", provider_retry, t),
            Activity("collect_serp", collect_serp, "SERP collection", provider_retry, t),
            Activity("collect_gerp", collect_gerp, "GERP collection", provider_retry, t * 2),
            Activity("normalise", normalise, "Normalisation", NO_RETRY, t),
            Activity("resolve_entities", resolve_entities, "Entity resolution", NO_RETRY, t),
            Activity("data_quality", data_quality, "Data-quality checks", NO_RETRY, t),
            Activity("compute_metrics", compute_metrics, "Metrics", NO_RETRY, t),
            Activity("gap_detection", detect_gaps, "Gap detection", NO_RETRY, t),
            Activity("counter_evidence", counter_evidence, "Counter-evidence", NO_RETRY, t),
            Activity("admission_gates", admission_gates, "Admission gates", NO_RETRY, t),
            Activity("scoring", score_candidates, "Scoring", NO_RETRY, t),
            Activity("create_cards", create_cards, "Opportunity Card creation", NO_RETRY, t),
            Activity("evaluation", run_evaluation, "Evaluation", NO_RETRY, t),
        ),
    )


def start_discovery(deps: DiscoveryDeps, req: CollectionRequest, *, force_new: bool = False) -> CollectionRun:
    platform = deps.platform
    try:
        budget = budget_for(deps.pack, req)
    except BudgetExceeded:
        budget = deps.pack.market(req.market).tiers[req.tier].max_budget_usd
    try:
        estimate: CostEstimate | None = _estimate(deps, req)
    except (BudgetExceeded, KeyError):
        estimate = None
    workflow = build_workflow(platform.settings.activity_timeout_s)
    return platform.runtime.start(
        workflow,
        idempotency_key=req.idempotency_key(),
        request=req.model_dump(mode="json"),
        budget_usd=budget,
        deps=deps,
        attributes={
            "market": req.market,
            "tier": req.tier,
            "domain_pack": req.domain_pack,
            "provider.mode": deps.provider_mode,
        },
        cost_estimate=estimate,
        force_new=force_new,
    )


def resume_discovery(deps: DiscoveryDeps, run_id: str) -> CollectionRun:
    run = deps.platform.runtime.get(run_id)
    if run is None:
        raise KeyError(run_id)
    if run.status == RunStatus.SUCCEEDED:
        return run
    req = CollectionRequest.model_validate(run.request)
    return deps.platform.runtime.resume(
        run_id,
        build_workflow(deps.platform.settings.activity_timeout_s),
        deps,
        {"market": req.market, "tier": req.tier, "domain_pack": req.domain_pack, "provider.mode": deps.provider_mode},
    )
