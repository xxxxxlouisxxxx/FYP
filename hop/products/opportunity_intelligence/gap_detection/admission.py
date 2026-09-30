"""Opportunity admission gates (spec 7.1). A candidate becomes a Draft Opportunity Card only if all pass."""

from __future__ import annotations

from typing import Any

from hop.platform.common_contracts import DataQualityStatus
from hop.platform.workflow_runtime import RunContext
from hop.products.opportunity_intelligence.config import AdmissionPolicy
from hop.products.opportunity_intelligence.contracts import (
    AdmissionOutcome,
    CounterEvidenceStatus,
    GapCandidate,
    GateResult,
)
from hop.products.opportunity_intelligence.deps import DiscoveryDeps

CRITICAL_GATES = {"lineage_verified", "data_quality", "untrusted_content"}


def evaluate_gates(
    c: GapCandidate,
    policy: AdmissionPolicy,
    *,
    lineage_failures: list[str],
    untrusted_support: list[str],
    score_version: str | None,
    critical_flags: list[str],
) -> list[GateResult]:
    def gate(gate_id: str, label: str, passed: bool, detail: str) -> GateResult:
        return GateResult(
            gate_id=gate_id,
            label=label,
            passed=passed,
            detail=detail,
            severity="critical" if gate_id in CRITICAL_GATES else "standard",
        )

    fams = sorted(f.value for f in c.observed_signal_families)
    min_n = c.metrics.get("quality.min_sample_n")
    n_val = min_n.value if min_n is not None and min_n.is_observed else None
    amb = c.entity_ambiguity_rate
    return [
        gate(
            "independent_signal_families",
            "At least two independent signal families",
            len(fams) >= policy.min_signal_families,
            f"observed families: {fams or 'none'} (need {policy.min_signal_families})",
        ),
        gate(
            "supporting_evidence",
            "Supporting evidence linked",
            bool(c.supporting_evidence_ids),
            f"{len(c.supporting_evidence_ids)} supporting evidence item(s)",
        ),
        gate(
            "lineage_verified",
            "Every cited evidence item traces to a hashed raw payload",
            not lineage_failures,
            "all lineage verified" if not lineage_failures else f"lineage failures: {lineage_failures[:3]}",
        ),
        gate(
            "counter_evidence_checked",
            "Counter-evidence search completed",
            (not policy.require_counter_evidence) or c.counter_evidence_status == CounterEvidenceStatus.COMPLETED,
            f"status {c.counter_evidence_status.value}",
        ),
        gate(
            "entity_ambiguity",
            "Entity ambiguity below threshold",
            amb is None or amb <= policy.max_entity_ambiguity_rate,
            f"ambiguity rate {'n/a (no entity mentions)' if amb is None else f'{amb:.1%}'} "
            f"(max {policy.max_entity_ambiguity_rate:.0%}); ambiguous aliases are flagged, never merged",
        ),
        gate(
            "data_quality",
            "No critical data-quality failure",
            c.data_quality_status != DataQualityStatus.FAILED_CRITICAL and not critical_flags,
            f"need data quality {c.data_quality_status.value}"
            + (f"; critical flags {critical_flags}" if critical_flags else ""),
        ),
        gate(
            "sample_size",
            "Minimum sample size met",
            n_val is not None and n_val >= policy.min_sample_n,
            f"smallest key-rate sample n={n_val if n_val is not None else 'missing'} (min {policy.min_sample_n})",
        ),
        gate(
            "versions_recorded",
            "Rule and score versions recorded",
            (not policy.require_rule_and_score_versions) or bool(c.rule_version and c.rule_set_id and score_version),
            f"{c.rule_set_id}/{c.rule_id}@{c.rule_version}; {score_version or 'no score version'}",
        ),
        gate(
            "untrusted_content",
            "No quarantined or injection-flagged evidence used as support",
            not untrusted_support,
            "clean" if not untrusted_support else f"{len(untrusted_support)} untrusted item(s) in support",
        ),
        gate(
            "freshness",
            "Evidence within market freshness policy",
            c.freshness_days is not None and c.freshness_days <= c.freshness_policy_days,
            f"oldest observation {c.freshness_days if c.freshness_days is not None else 'missing'} days "
            f"(policy {c.freshness_policy_days} days)",
        ),
    ]


def decide(gates: list[GateResult]) -> tuple[AdmissionOutcome, str]:
    failed = [g for g in gates if not g.passed]
    if not failed:
        return AdmissionOutcome.ADMITTED, "all admission gates passed"
    critical = [g for g in failed if g.severity == "critical"]
    if critical:
        return AdmissionOutcome.QUARANTINED, "critical gate failed: " + ", ".join(g.gate_id for g in critical)
    if any(g.gate_id == "supporting_evidence" for g in failed):
        return AdmissionOutcome.REJECTED, "no supporting evidence"
    return AdmissionOutcome.NOT_ADMITTED, "failed: " + ", ".join(g.gate_id for g in failed)


def admission_gates(ctx: RunContext) -> dict[str, Any]:
    deps: DiscoveryDeps = ctx.deps
    repo, evidence, cfg = deps.repo, deps.platform.evidence, deps.config
    cache: dict[str, str] = {}
    outcomes: dict[str, int] = {}
    with ctx.span("Admission gates", {"policy.version": cfg.admission.version}):
        for c in repo.candidates(ctx.run_id):
            lineage_failures: list[str] = []
            untrusted: list[str] = []
            for eid in [*c.supporting_evidence_ids, *c.counter_evidence_ids]:
                res = evidence.verify_lineage(eid, cache)
                if not res.valid:
                    lineage_failures.append(f"{eid}: {res.reason}")
            for eid in c.supporting_evidence_ids:
                item = evidence.get(eid)
                if item is not None and (
                    item.data_quality_status == DataQualityStatus.QUARANTINED
                    or "PROMPT_INJECTION_SUSPECTED" in item.quality_flags
                ):
                    untrusted.append(eid)
            gates = evaluate_gates(
                c,
                cfg.admission,
                lineage_failures=lineage_failures,
                untrusted_support=untrusted,
                score_version=cfg.scoring.score_version,
                critical_flags=sorted(set(cfg.admission.critical_quality_flags) & _need_flags(ctx, c.need_id)),
            )
            outcome, reason = decide(gates)
            c.gate_results = gates
            c.admission = outcome
            c.admission_reason = reason
            repo.upsert_candidate(c)
            outcomes[outcome.value] = outcomes.get(outcome.value, 0) + 1
    return {"outcomes": outcomes, "policy_version": cfg.admission.version}


def _need_flags(ctx: RunContext, need_id: str) -> set[str]:
    from hop.products.opportunity_intelligence.deps import step_output

    return set(step_output(ctx, "data_quality").get("needs", {}).get(need_id, {}).get("flags", []))
