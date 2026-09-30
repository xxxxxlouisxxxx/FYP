from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from hop.platform.common_contracts import RunStatus, StepStatus, ValueState
from hop.products.opportunity_intelligence.contracts import AdmissionOutcome, OpportunityStatus
from hop.products.opportunity_intelligence.metrics import load_metrics
from hop.products.opportunity_intelligence.pipeline import build_workflow, resume_discovery, start_discovery
from tests.conftest import Discovery, hk_request, make_app

SPEC_SPANS = {
    "Configuration validation",
    "Cost estimation",
    "SERP collection",
    "GERP collection",
    "Normalisation",
    "Entity resolution",
    "Data-quality checks",
    "Gap detection",
    "Counter-evidence",
    "Admission gates",
    "Scoring",
    "Opportunity Card creation",
    "Model call",
}


def test_sandbox_run_produces_draft_cards(discovery: Discovery) -> None:
    run = discovery.run
    assert run.status == RunStatus.SUCCEEDED, run.error
    assert [s.name for s in run.steps] == [a.name for a in build_workflow(60).activities]
    assert all(s.status == StepStatus.SUCCEEDED for s in run.steps)
    cards = discovery.app.repo.cards(run_id=run.run_id)
    assert cards and all(c.status == OpportunityStatus.DRAFT for c in cards)
    assert {c.priority for c in cards} >= {"HIGH", "MEDIUM"}
    assert 0 < run.actual_cost_usd <= run.budget_usd


def test_cards_are_backed_by_verifiable_evidence(discovery: Discovery) -> None:
    evidence = discovery.app.platform.evidence
    for card in discovery.app.repo.cards(run_id=discovery.run.run_id):
        assert card.supporting_evidence_ids, card.card_id
        assert card.counter_evidence_ids or card.limitations, "counter-evidence or limitations are required"
        assert card.score.score_version and card.rule_version
        for eid in card.supporting_evidence_ids:
            assert evidence.verify_lineage(eid).valid, eid
        linked = set(card.supporting_evidence_ids) | set(card.counter_evidence_ids)
        assert card.observed and all(s.evidence_ids for s in card.observed)
        for statement in [*card.observed, *card.inferred, *card.unknowns, *card.limitations]:
            assert set(statement.evidence_ids) <= linked
        assert card.explanation.validated
        assert set(card.explanation.cited_evidence_ids) <= linked


def test_admission_gates_filter_candidates(discovery: Discovery) -> None:
    repo, run_id = discovery.app.repo, discovery.run.run_id
    candidates = repo.candidates(run_id)
    admitted = [c for c in candidates if c.admission == AdmissionOutcome.ADMITTED]
    rejected = [c for c in candidates if c.admission != AdmissionOutcome.ADMITTED]
    assert admitted and rejected
    assert len(repo.cards(run_id=run_id)) == len(admitted)
    assert any("independent_signal_families" in (c.admission_reason or "") for c in rejected)
    assert any("entity_ambiguity" in (c.admission_reason or "") for c in rejected)
    for c in admitted:
        assert all(g.passed for g in c.gate_results if g.severity == "critical")


def test_missing_values_stay_missing(discovery: Discovery) -> None:
    records = {r["need_id"]: load_metrics(r) for r in discovery.app.repo.metrics(discovery.run.run_id, scope="need")}
    assert records["budget_beginner"]["demand.index"].state == ValueState.NOT_COLLECTED
    assert records["budget_beginner"]["demand.index"].value is None
    assert records["vegan_sustainable"]["serp.supply_share"].state == ValueState.PROVIDER_ERROR
    cards = discovery.app.repo.cards(run_id=discovery.run.run_id)
    assert not [c for c in cards if c.need_id == "budget_beginner" and "DEMAND" in c.gap_family]


def test_trace_covers_the_spec_spans_and_costs_reconcile(discovery: Discovery) -> None:
    platform = discovery.app.platform
    spans = platform.telemetry.spans_for_trace(discovery.run.trace_id)
    assert {s["name"] for s in spans} >= SPEC_SPANS
    assert platform.costs.total_for_run(discovery.run.run_id) == discovery.run.actual_cost_usd
    assert platform.audit.verify_chain()[0]


def test_same_request_is_idempotent(fresh_discovery: Discovery) -> None:
    app = fresh_discovery.app
    again = start_discovery(app.discovery_deps(), hk_request())
    first = start_discovery(app.discovery_deps(), hk_request())
    assert again.run_id == first.run_id
    assert len(app.repo.cards(run_id=first.run_id)) == len(app.repo.cards(run_id=fresh_discovery.run.run_id))


def test_budget_rejection(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    run = start_discovery(app.discovery_deps(), hk_request(budget_usd=0.01), force_new=True)
    assert run.status == RunStatus.REJECTED_BUDGET
    assert app.repo.cards(run_id=run.run_id) == []
    assert app.platform.costs.total_for_run(run.run_id) == 0


def test_kill_switch_mid_run_then_resume_from_checkpoints(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    deps = app.discovery_deps()
    original = deps.serp_provider

    class EngageOnFetch:
        def __init__(self, inner) -> None:  # noqa: ANN001
            self.inner = inner

        def __getattr__(self, name: str):  # noqa: ANN204
            return getattr(self.inner, name)

        def fetch_serp(self, **kwargs):  # noqa: ANN003, ANN202
            app.platform.kill_switch.set(True, actor="ops", reason="test incident")
            return self.inner.fetch_serp(**kwargs)

    def engage_then_serp(run_id: str) -> EngageOnFetch:
        return EngageOnFetch(original(run_id))

    killed = start_discovery(replace(deps, serp_provider=engage_then_serp), hk_request(), force_new=True)
    assert killed.status == RunStatus.KILLED
    assert app.repo.cards(run_id=killed.run_id) == []
    assert any(d["run_id"] == killed.run_id for d in app.platform.runtime.dead_letters())
    done_before = set(app.platform.runtime.checkpoints(killed.run_id))
    assert {"validate_config", "estimate_cost", "collect_demand"} <= done_before

    app.platform.kill_switch.set(False, actor="ops", reason="resolved")
    resumed = resume_discovery(deps, killed.run_id)
    assert resumed.status == RunStatus.SUCCEEDED, resumed.error
    assert resumed.resumed_count == 1
    restored = {s.name for s in resumed.steps if s.restored_from_checkpoint}
    assert done_before <= restored
    assert app.repo.cards(run_id=resumed.run_id)


def test_second_market_by_configuration(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    run = start_discovery(app.discovery_deps(), hk_request(market="SG"), force_new=True)
    assert run.status == RunStatus.SUCCEEDED, run.error
    assert all(c.market == "SG" for c in app.repo.cards(run_id=run.run_id))
