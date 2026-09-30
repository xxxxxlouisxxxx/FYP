"""Evidence-linked explanation and Draft Opportunity Card creation.

Statements are generated deterministically from metrics and carry the evidence ids they rest on.
The optional model summary (via the gateway) is validated: it may cite only the card's evidence ids and
may not introduce numbers that are absent from the supplied facts. Otherwise the template summary is used.
"""

from __future__ import annotations

import re
from typing import Any

from hop.platform.common_contracts import ActorType, EvidenceItem, EvidenceType, MeasuredValue, Proportion, stable_id
from hop.platform.workflow_runtime import RunContext
from hop.products.opportunity_intelligence.contracts import (
    AdmissionOutcome,
    Explanation,
    GapCandidate,
    OpportunityCard,
    Statement,
    StatementKind,
)
from hop.products.opportunity_intelligence.deps import DiscoveryDeps
from hop.products.opportunity_intelligence.schemas import ExplanationOutput
from hop.products.opportunity_intelligence.scoring.activity import evidence_confidence

FAMILY_TITLES = {
    "HIGH_DEMAND_WEAK_SERP_SUPPLY": "strong search demand, weak product supply in search results",
    "HIGH_DEMAND_WEAK_GERP_COVERAGE": "strong search demand, few concrete AI-answer recommendations",
    "NO_DOMINANT_SUPPLYING_BRAND": "no dominant brand in search visibility",
    "GERP_RECOMMENDATION_WEAK_SEARCH_SUPPORT": "AI answers recommend products their sources do not show in search",
    "SERP_VISIBLE_GERP_ABSENT": "visible in search but absent from AI-answer recommendations",
    "WEAK_SERP_SUPPLY_SINGLE_SIGNAL": "weak product supply in search results (single signal)",
}
NEXT_ACTIONS = {
    "HIGH_DEMAND_WEAK_SERP_SUPPLY": "Run a Tier-B re-collection (desktop + mobile) and a supplier scan with HKTDC sourcing to "
    "confirm whether on-need products exist but are not visible.",
    "HIGH_DEMAND_WEAK_GERP_COVERAGE": "Repeat GERP observation with 5 repeats (Tier B) and a second approved model to confirm "
    "low recommendation coverage is stable.",
    "NO_DOMINANT_SUPPLYING_BRAND": "Collect a second SERP snapshot to measure volatility and interview buyers on brand loyalty.",
    "GERP_RECOMMENDATION_WEAK_SEARCH_SUPPORT": "Inspect the cited sources and check whether recommended products are "
    "purchasable in-market.",
    "SERP_VISIBLE_GERP_ABSENT": "Review the brand's product content and third-party citations, then repeat GERP observation "
    "to rule out sampling noise.",
}
KEY_SAMPLE_METRICS = (
    "demand.search_volume",
    "demand.index",
    "serp.supply_share",
    "serp.top3_supply_share",
    "gerp.recommendation_coverage",
    "gerp.primary_rate",
    "gerp.exclusion_rate",
    "gerp.stability",
    "serp.brand_share",
    "gerp.brand_recommendation_rate",
    "gerp.answers",
    "quality.min_sample_n",
)
UNKNOWN_CANDIDATES = (
    "demand.trend_yoy",
    "serp.volatility",
    "gerp.stability",
    "gerp.citation_support",
    "serp.brand_hhi",
    "demand.coverage",
)
_NUM = re.compile(r"\d+(?:[.,]\d+)*")


def _ids(items: list[EvidenceItem], *types: EvidenceType) -> list[str]:
    return [e.evidence_id for e in items if e.evidence_type in types]


def _p(m: Any) -> str:
    if isinstance(m, Proportion):
        return m.display()
    if isinstance(m, MeasuredValue):
        return m.display("{:,.2f}")
    return "missing"


def confidence_label(c: GapCandidate) -> str:
    min_n = c.metrics.get("quality.min_sample_n")
    n = min_n.value if min_n is not None and min_n.is_observed and min_n.value is not None else 0
    conf = evidence_confidence(c)
    if n < 10:
        return "exploratory"
    if conf >= 0.8 and n >= 100:
        return "high"
    if conf >= 0.6 and n >= 30:
        return "moderate"
    return "low"


def build_statements(
    c: GapCandidate, support: list[EvidenceItem], brand_name: str | None, simulated: bool
) -> dict[str, list[Statement]]:
    m = c.metrics
    observed: list[Statement] = []
    demand_ids = _ids(support, EvidenceType.DEMAND_SIGNAL)
    if demand_ids and m.get("demand.search_volume") and m["demand.search_volume"].is_observed:
        vol = m["demand.search_volume"]
        observed.append(
            Statement(
                kind=StatementKind.OBSERVED,
                evidence_ids=demand_ids,
                text=(
                    f"Search demand: {int(vol.value or 0):,} monthly searches across {vol.n} quer{'y' if vol.n == 1 else 'ies'} "
                    f"(demand index {m['demand.index'].display('{:.2f}')})."
                ),
            )
        )
    serp_ids = _ids(support, EvidenceType.SERP_RESULT)
    if serp_ids:
        if c.brand_id:
            text = f"SERP: {brand_name} is associated with {_p(m.get('serp.brand_share'))} of top-10 organic results."
        elif c.gap_family == "NO_DOMINANT_SUPPLYING_BRAND":
            text = (
                f"SERP: brand visibility is fragmented (HHI {_p(m.get('serp.brand_hhi'))} over "
                f"{_p(m.get('serp.brand_mentions'))} brand-result associations)."
            )
        else:
            text = (
                f"SERP: on-need product supply pages make up {_p(m.get('serp.supply_share'))} of top-10 organic "
                f"results; top-3 supply share {_p(m.get('serp.top3_supply_share'))}."
            )
        observed.append(Statement(kind=StatementKind.OBSERVED, text=text, evidence_ids=serp_ids))
    gerp_ids = _ids(support, EvidenceType.GERP_ANSWER, EvidenceType.GERP_CITATION)
    if gerp_ids:
        if c.brand_id:
            text = (
                f"GERP: {brand_name} was recommended in {_p(m.get('gerp.brand_recommendation_rate'))} of generative "
                f"answers (mentions {_p(m.get('gerp.brand_mention_rate'))}, exclusions "
                f"{_p(m.get('gerp.brand_exclusion_rate'))})."
            )
        elif c.gap_family == "GERP_RECOMMENDATION_WEAK_SEARCH_SUPPORT":
            text = (
                f"GERP: answers recommend products in {_p(m.get('gerp.recommendation_coverage'))} of cases, but only "
                f"{_p(m.get('gerp.citation_support'))} of cited sources appear in the same query's top-10 SERP."
            )
        else:
            text = (
                f"GERP: {_p(m.get('gerp.recommendation_coverage'))} of generative answers give a concrete product "
                f"recommendation; mention-only {_p(m.get('gerp.mention_only_rate'))}."
            )
        observed.append(Statement(kind=StatementKind.OBSERVED, text=text, evidence_ids=gerp_ids))
    conds = "; ".join(f"{x['metric']} {x['op']} {x['threshold']} (observed {x['observed']})" for x in c.condition_trace)
    inferred = [
        Statement(
            kind=StatementKind.INFERRED,
            evidence_ids=list(c.supporting_evidence_ids),
            text=(
                f"Rule {c.rule_id}@{c.rule_version} ({c.rule_set_id}) matched: {conds}. This suggests a hidden opportunity; "
                f"it is not proof of unmet demand."
            ),
        )
    ]
    unknowns = []
    for key in UNKNOWN_CANDIDATES:
        v = m.get(key)
        if v is not None and not v.is_observed:
            unknowns.append(
                Statement(kind=StatementKind.UNKNOWN, text=f"{key}: {v.state.value} - {v.reason or 'not available'}")
            )
    limitations = []
    if simulated:
        limitations.append(
            Statement(
                kind=StatementKind.LIMITATION,
                text=(
                    "Sandbox run: provider and model observations are recorded fixtures with simulated cost, not live data."
                ),
            )
        )
    if confidence_label(c) == "exploratory":
        limitations.append(
            Statement(
                kind=StatementKind.LIMITATION,
                text=(
                    "Exploratory sample: at least one key rate rests on fewer than 10 observations; wide confidence intervals."
                ),
            )
        )
    for note in c.counter_evidence_notes:
        limitations.append(
            Statement(
                kind=StatementKind.LIMITATION,
                text=f"Counter-evidence: {note}.",
                evidence_ids=list(c.counter_evidence_ids),
            )
        )
    return {"observed": observed, "inferred": inferred, "unknowns": unknowns, "limitations": limitations}


def validate_summary(summary: str, cited: list[str], allowed_ids: set[str], facts_text: str) -> list[str]:
    notes = []
    bad_ids = sorted(set(cited) - allowed_ids)
    if bad_ids:
        notes.append(f"cites evidence ids not on the card: {bad_ids[:3]}")
    fact_numbers = {n.replace(",", "") for n in _NUM.findall(facts_text)}
    new_numbers = sorted({n.replace(",", "") for n in _NUM.findall(summary)} - fact_numbers)
    if new_numbers:
        notes.append(f"introduces numbers absent from facts: {new_numbers[:5]}")
    return notes


def explain(
    ctx: RunContext, deps: DiscoveryDeps, title: str, statements: dict[str, list[Statement]], allowed_ids: set[str]
) -> Explanation:
    prompt = deps.pack.prompt("opportunity_explanation")
    facts = {
        "title": title,
        "observed": [s.model_dump() for s in statements["observed"]],
        "inferred": [s.model_dump() for s in statements["inferred"]],
    }
    facts_text = title + " " + " ".join(s.text for group in statements.values() for s in group)
    template = " ".join([title + "."] + [s.text for s in statements["observed"]])
    result = deps.platform.gateway.invoke(
        capability_id="opportunity.explanation",
        prompt=prompt,
        variables={"facts": facts},
        output_model=ExplanationOutput,
        run=ctx,
    )
    if result.ok and result.output:
        notes = validate_summary(
            result.output["summary"], result.output.get("cited_evidence_ids", []), allowed_ids, facts_text
        )
        if not notes:
            return Explanation(
                summary=result.output["summary"],
                generator="model_gateway",
                model_id=result.model_id,
                prompt_id=result.prompt_id,
                prompt_version=result.prompt_version,
                cited_evidence_ids=result.output.get("cited_evidence_ids", []),
                validated=True,
            )
        return Explanation(
            summary=template,
            generator="template",
            model_id=result.model_id,
            prompt_id=result.prompt_id,
            prompt_version=result.prompt_version,
            cited_evidence_ids=sorted(allowed_ids)[:10],
            validated=True,
            validation_notes=["model summary rejected: " + "; ".join(notes)],
        )
    return Explanation(
        summary=template,
        generator="template",
        prompt_id=prompt.prompt_id,
        prompt_version=prompt.version,
        cited_evidence_ids=sorted(allowed_ids)[:10],
        validated=True,
        validation_notes=[f"model abstained ({result.abstention_reason}); template summary used"],
    )


def create_cards(ctx: RunContext) -> dict[str, Any]:
    deps: DiscoveryDeps = ctx.deps
    repo, evidence, resolver = deps.repo, deps.platform.evidence, deps.resolver
    simulated = (
        deps.provider_mode == "sandbox" or deps.platform.gateway.models[deps.platform.gateway.default_model].simulated
    )
    created = skipped = 0
    for c in repo.candidates(ctx.run_id, admission=AdmissionOutcome.ADMITTED.value):
        if c.score is None:
            continue
        card_id = stable_id("opp", c.candidate_id)
        if repo.card(card_id) is not None:
            skipped += 1
            continue
        ctx.check_controls()
        support = [e for e in (evidence.get(i) for i in c.supporting_evidence_ids) if e is not None]
        brand = resolver.name(c.brand_id) if c.brand_id else None
        title = (
            f"{brand}: {FAMILY_TITLES.get(c.gap_family, c.gap_family)} - {c.need_label} ({c.market})"
            if brand
            else f"{c.need_label} ({c.market}): {FAMILY_TITLES.get(c.gap_family, c.gap_family)}"
        )
        statements = build_statements(c, support, brand, simulated)
        allowed = set(c.supporting_evidence_ids) | set(c.counter_evidence_ids)
        with ctx.span("Explanation", {"candidate.id": c.candidate_id}):
            explanation = explain(ctx, deps, title, statements, allowed)
        high = c.score.priority == "HIGH"
        card = OpportunityCard(
            card_id=card_id,
            candidate_id=c.candidate_id,
            run_id=c.run_id,
            trace_id=ctx.trace_id,
            title=title,
            market=c.market,
            need_id=c.need_id,
            need_label=c.need_label,
            brand_id=c.brand_id,
            attribute_ids=c.attribute_ids,
            gap_family=c.gap_family,
            priority=c.score.priority,
            score=c.score,
            confidence_label=confidence_label(c),  # type: ignore[arg-type]
            evidence_confidence=evidence_confidence(c),
            sample_summary={k: c.metrics[k] for k in KEY_SAMPLE_METRICS if k in c.metrics},
            **statements,
            supporting_evidence_ids=c.supporting_evidence_ids,
            counter_evidence_ids=c.counter_evidence_ids,
            counter_evidence_status=c.counter_evidence_status,
            explanation=explanation,
            next_validation_action=NEXT_ACTIONS.get(c.gap_family, "Collect a second independent signal family."),
            required_approver_role="review_board" if high else "analyst",
            rule_set_id=c.rule_set_id,
            rule_id=c.rule_id,
            rule_version=c.rule_version,
            score_version=c.score.score_version,
            domain_pack=c.domain_pack,
            domain_pack_version=c.domain_pack_version,
            prompt_versions={p.prompt_id: p.version for p in deps.pack.prompts.values()},
            model_ids=sorted(
                {e.model_id for e in support if e.model_id}
                | ({explanation.model_id} if explanation.model_id else set())
            ),
            lineage_verified=all(g.passed for g in c.gate_results if g.gate_id == "lineage_verified"),
        )
        repo.save_card(card)
        deps.platform.audit.record(
            actor="opportunity_intelligence",
            actor_type=ActorType.SYSTEM,
            action="opportunity.created",
            resource_type="opportunity_card",
            resource_id=card.card_id,
            details={"priority": card.priority, "score": card.score.total, "status": "DRAFT"},
            trace_id=ctx.trace_id,
        )
        created += 1
    return {"cards_created": created, "already_present": skipped}
