"""Counter-evidence agent (bounded; capability ``opportunity.counter_evidence``).

Searches only acquired evidence for facts that weaken a candidate. Strength is a deterministic
0-1 number derived from the counter-evidence found; it feeds the ``strong_counter_evidence`` penalty
and the admission gate that requires counter-evidence to have been checked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hop.platform.common_contracts import EvidenceItem, EvidenceType, MeasuredValue
from hop.platform.policy_engine import PolicyViolation
from hop.platform.policy_engine.tools import AgentSession, AgentTimeout, MaxStepsExceeded, ToolArgumentError
from hop.platform.workflow_runtime import RunContext
from hop.products.opportunity_intelligence.contracts import CounterEvidenceStatus, GapCandidate
from hop.products.opportunity_intelligence.deps import DiscoveryDeps

CAPABILITY_ID = "opportunity.counter_evidence"
RECOMMENDATION_TYPES = [EvidenceType.GERP_PRIMARY_RECOMMENDATION, EvidenceType.GERP_SUPPORTING_RECOMMENDATION]


@dataclass
class CounterFinding:
    evidence: list[EvidenceItem] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    strength: float = 0.0

    def add(self, items: list[EvidenceItem], note: str, weight: float) -> None:
        if not items:
            return
        self.evidence.extend(items)
        self.notes.append(note)
        self.strength = min(1.0, self.strength + weight)


def _rate(metrics: dict[str, Any], name: str) -> float | None:
    m = metrics.get(name)
    if m is None or not m.is_observed:
        return None
    return getattr(m, "rate", None) if getattr(m, "kind", "") == "proportion" else m.value


def investigate(session: AgentSession, c: GapCandidate) -> CounterFinding:
    f = CounterFinding()
    taxonomy = session.call("taxonomy.lookup", need_id=c.need_id)
    family = c.gap_family

    if family in ("HIGH_DEMAND_WEAK_SERP_SUPPLY", "WEAK_SERP_SUPPLY_SINGLE_SIGNAL", "NO_DOMINANT_SUPPLYING_BRAND"):
        serp = session.call(
            "evidence.search", run_id=c.run_id, need_id=c.need_id, evidence_types=[EvidenceType.SERP_RESULT]
        )
        top_supply = [e for e in serp if e.attributes.get("supply") and e.attributes.get("rank", 99) <= 3]
        f.add(
            top_supply[:3],
            f"{len(top_supply)} on-need product page(s) already rank in the top 3",
            0.2 * len(top_supply[:3]),
        )
        recs = session.call(
            "evidence.search",
            run_id=c.run_id,
            need_id=c.need_id,
            evidence_types=[EvidenceType.GERP_PRIMARY_RECOMMENDATION],
        )
        f.add(
            recs[:3],
            f"generative engines already name a primary pick in {len(recs)} answer span(s)",
            0.1 * min(3, len(recs)),
        )
    if family == "HIGH_DEMAND_WEAK_GERP_COVERAGE":
        recs = session.call("evidence.search", run_id=c.run_id, need_id=c.need_id, evidence_types=RECOMMENDATION_TYPES)
        f.add(
            recs[:4],
            f"{len(recs)} recommendation span(s) show some answers do recommend products",
            0.1 * min(4, len(recs)),
        )
        serp = session.call(
            "evidence.search", run_id=c.run_id, need_id=c.need_id, evidence_types=[EvidenceType.SERP_RESULT]
        )
        supply = [e for e in serp if e.attributes.get("supply")]
        f.add(
            supply[:3], f"{len(supply)} on-need product supply result(s) exist in the SERP", 0.05 * min(3, len(supply))
        )
    if family == "SERP_VISIBLE_GERP_ABSENT" and c.brand_id:
        excl = session.call(
            "evidence.search", run_id=c.run_id, need_id=c.need_id, evidence_types=[EvidenceType.GERP_EXCLUSION]
        )
        excl = [e for e in excl if c.brand_id in e.entity_refs]
        f.add(
            excl[:3],
            f"generative answers explicitly advise against the brand ({len(excl)} span(s)) - absence may be deliberate",
            0.35 * min(2, len(excl)),
        )
        ment = session.call(
            "evidence.search", run_id=c.run_id, need_id=c.need_id, evidence_types=[EvidenceType.GERP_MENTION]
        )
        ment = [e for e in ment if c.brand_id in e.entity_refs]
        f.add(ment[:2], f"the brand is mentioned (not recommended) in {len(ment)} answer span(s)", 0.1)
    if family == "GERP_RECOMMENDATION_WEAK_SEARCH_SUPPORT":
        cites = session.call(
            "evidence.search", run_id=c.run_id, need_id=c.need_id, evidence_types=[EvidenceType.GERP_CITATION]
        )
        serp = session.call(
            "evidence.search", run_id=c.run_id, need_id=c.need_id, evidence_types=[EvidenceType.SERP_RESULT]
        )
        domains = {str(e.attributes.get("domain", "")).removeprefix("www.") for e in serp}
        backed = [e for e in cites if str(e.attributes.get("domain", "")).removeprefix("www.") in domains]
        f.add(backed[:3], f"{len(backed)} cited source(s) do appear in the SERP", 0.15 * min(3, len(backed)))

    if "demand" in [s.value for s in c.signal_families]:
        demand = session.call(
            "evidence.search", run_id=c.run_id, need_id=c.need_id, evidence_types=[EvidenceType.DEMAND_SIGNAL]
        )
        falling = [e for e in demand if (e.attributes.get("trend_yoy") or 0) <= -0.15]
        f.add(falling, "search demand fell by 15% or more year-on-year for some queries", 0.25)
    quarantined = session.call(
        "evidence.search",
        run_id=c.run_id,
        need_id=c.need_id,
        evidence_types=[EvidenceType.SERP_RESULT],
        include_quarantined=True,
    )
    q_ids = [e for e in quarantined if e.data_quality_status.value == "QUARANTINED"]
    if q_ids:
        f.notes.append(f"{len(q_ids)} SERP result(s) quarantined for suspected prompt injection were excluded")
    if taxonomy.get("found") and taxonomy["need"].get("regulatory_flags"):
        f.notes.append(
            f"need carries regulatory flags {taxonomy['need']['regulatory_flags']}: product claims need review"
        )
    f.strength = round(f.strength, 4)
    seen: set[str] = set()
    f.evidence = [e for e in f.evidence if not (e.evidence_id in seen or seen.add(e.evidence_id))]  # type: ignore[func-returns-value]
    return f


def counter_evidence(ctx: RunContext) -> dict[str, Any]:
    deps: DiscoveryDeps = ctx.deps
    repo = deps.repo
    done = unavailable = 0
    strong = 0
    for c in repo.candidates(ctx.run_id):
        ctx.check_controls()
        with ctx.span("Counter-evidence search", {"candidate.id": c.candidate_id, "capability.id": CAPABILITY_ID}):
            try:
                session = AgentSession(
                    policy=deps.platform.policy,
                    tools=deps.tools,
                    telemetry=deps.platform.telemetry,
                    capability_id=CAPABILITY_ID,
                    run_id=ctx.run_id,
                )
                finding = investigate(session, c)
            except (PolicyViolation, MaxStepsExceeded, AgentTimeout, ToolArgumentError) as exc:
                c.counter_evidence_status = CounterEvidenceStatus.UNAVAILABLE
                c.counter_evidence_notes = [f"counter-evidence agent unavailable: {type(exc).__name__}: {exc}"[:300]]
                c.metrics["counter.strength"] = MeasuredValue.missing(
                    "PROVIDER_ERROR", "counter-evidence agent did not complete"
                )  # type: ignore[arg-type]
                repo.upsert_candidate(c)
                unavailable += 1
                continue
        c.counter_evidence_status = CounterEvidenceStatus.COMPLETED
        c.counter_evidence_ids = [e.evidence_id for e in finding.evidence]
        c.counter_evidence_strength = finding.strength
        c.counter_evidence_notes = finding.notes or ["no counter-evidence found in acquired evidence"]
        c.metrics["counter.strength"] = MeasuredValue.observed(finding.strength, n=len(finding.evidence))
        repo.upsert_candidate(c)
        done += 1
        strong += finding.strength >= 0.5
    return {"completed": done, "unavailable": unavailable, "strong_counter_evidence": strong}
