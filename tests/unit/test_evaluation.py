from __future__ import annotations

from hop.bootstrap import App
from hop.platform.evaluation import EvaluationHarness, EvaluatorOutput, RatchetSpec, ratchet_checks
from hop.products.opportunity_intelligence.evaluation import run_suites

RATCHET = RatchetSpec("f1", minimum=0.8, maximum_regression=0.02, secondary_metrics={"recall": 0.7})


def test_ratchet_blocks_regression_against_champion() -> None:
    checks = ratchet_checks({"f1": 0.85, "recall": 0.9}, RATCHET, {"f1": 0.9})
    assert [c["passed"] for c in checks] == [True, False, True]
    assert all(c["passed"] for c in ratchet_checks({"f1": 0.89, "recall": 0.9}, RATCHET, {"f1": 0.9}))


def test_missing_metric_fails_closed() -> None:
    checks = ratchet_checks({"f1": None}, RATCHET, None)
    assert not any(c["passed"] for c in checks)


def test_harness_persists_and_audits(app: App) -> None:
    p = app.platform
    harness = EvaluationHarness(p.store, p.telemetry, p.audit)
    result = harness.run(
        suite_id="toy",
        suite_version="1.0.0",
        partition="development",
        dataset={"version": "d1", "cases": [1, 2]},
        evaluator=lambda ds: EvaluatorOutput({"f1": 0.5, "recall": 0.9}, len(ds["cases"]), {"model": "m"}),
        ratchet=RATCHET,
    )
    assert not result.passed and result.dataset_version == "d1"
    assert harness.history("toy")[0].evaluation_run_id == result.evaluation_run_id
    assert any(e.action == "evaluation.run" and e.outcome == "FAILURE" for e in p.audit.list())


def test_packaged_golden_sets_pass_their_ratchets(app: App) -> None:
    p = app.platform
    harness = EvaluationHarness(p.store, p.telemetry, p.audit)
    results = run_suites(harness, p.gateway, app.pack, app.config, app.resolver, None)
    assert {r.suite_id for r in results} >= {"gerp-recommendation-v1", "entity-resolution-v1"}
    for r in results:
        assert r.passed, (r.suite_id, r.checks, r.failures[:3])
        assert r.n_cases > 0
