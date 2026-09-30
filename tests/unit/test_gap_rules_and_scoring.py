from __future__ import annotations

import pytest

from hop.platform.common_contracts import MeasuredValue, Proportion, ValueState
from hop.platform.domain_registry import load_domain_pack
from hop.products.opportunity_intelligence.config import (
    SCORE_COMPONENTS,
    Condition,
    GapRule,
    OpportunityConfig,
    load_opportunity_config,
)
from hop.products.opportunity_intelligence.gap_detection import evaluate_rule, run_rule_tests
from hop.products.opportunity_intelligence.scoring import score
from tests.conftest import REPO_ROOT


@pytest.fixture(scope="module")
def config() -> OpportunityConfig:
    return load_opportunity_config(load_domain_pack(REPO_ROOT / "domain_packs", "sports-footwear"))


def _rule() -> GapRule:
    return GapRule(
        rule_id="t",
        version="1.0.0",
        gap_family="X",
        scope="need",
        description="test",
        signal_families=["demand", "serp"],
        all_of=[
            Condition(metric="demand.index", op=">=", value=0.5),
            Condition(metric="serp.supply_share", op="<=", value=0.4, field="rate"),
        ],
    )


def test_every_packaged_rule_has_passing_tests(config: OpportunityConfig) -> None:
    for rule_set in config.rule_sets.values():
        report = run_rule_tests(rule_set)
        assert report.passed, [r for r in report.results if not r["passed"]]
        assert all(rule.tests for rule in rule_set.rules)


def test_rule_matches_only_when_every_condition_is_true() -> None:
    supply = Proportion.from_counts(2, 10)
    ev = evaluate_rule(_rule(), {"demand.index": MeasuredValue.observed(0.8), "serp.supply_share": supply})
    assert ev.matched
    ev = evaluate_rule(_rule(), {"demand.index": MeasuredValue.observed(0.3), "serp.supply_share": supply})
    assert not ev.matched and not ev.unknown


def test_missing_metric_is_unknown_not_zero() -> None:
    metrics = {
        "demand.index": MeasuredValue.missing(ValueState.NOT_COLLECTED, "provider returned null"),
        "serp.supply_share": Proportion.missing(ValueState.PROVIDER_ERROR, "SERP task failed"),
    }
    ev = evaluate_rule(_rule(), metrics)
    assert not ev.matched and ev.unknown
    assert [c.outcome for c in ev.conditions] == ["UNKNOWN", "UNKNOWN"]
    assert [c.state for c in ev.conditions] == ["NOT_COLLECTED", "PROVIDER_ERROR"]
    # A "<=" condition on a missing supply share would be TRUE if missing were coerced to zero.
    ev = evaluate_rule(_rule(), {"demand.index": MeasuredValue.observed(0.9)})
    assert ev.conditions[1].outcome == "UNKNOWN" and not ev.matched


def test_rubric_weights_sum_to_one(config: OpportunityConfig) -> None:
    assert set(config.scoring.weights) == set(SCORE_COMPONENTS)
    assert sum(config.scoring.weights.values()) == pytest.approx(1.0)


def _components(value: float | None = 0.8) -> dict[str, tuple[float | None, str, str]]:
    return dict.fromkeys(SCORE_COMPONENTS, (value, "test", "fixture"))


def _clean_metrics() -> dict[str, MeasuredValue]:
    return {
        "quality.freshness_ratio": MeasuredValue.observed(0.1),
        "quality.min_sample_n": MeasuredValue.observed(40),
        "gerp.stability": MeasuredValue.observed(0.9),
        "quality.entity_ambiguity_rate": MeasuredValue.observed(0),
        "counter.strength": MeasuredValue.observed(0.1),
        "demand.coverage": MeasuredValue.observed(1.0),
        "need.regulatory_flag": MeasuredValue.observed(0),
        "serp.brand_mentions": MeasuredValue.observed(20),
    }


def test_score_is_deterministic_and_decomposable(config: OpportunityConfig) -> None:
    a = score(_components(), _clean_metrics(), config.scoring)
    b = score(_components(), _clean_metrics(), config.scoring)
    assert a == b
    assert a.total == pytest.approx(0.8)
    assert a.gross == pytest.approx(sum(c.contribution for c in a.components))
    assert a.total_penalty == 0 and a.priority == "HIGH"
    assert a.score_version == config.scoring.score_version


def test_missing_component_contributes_nothing_and_is_labelled(config: OpportunityConfig) -> None:
    comps = _components()
    comps["gerp_recommendation_gap"] = (None, "gerp", "GERP not collected")
    s = score(comps, _clean_metrics(), config.scoring)
    part = next(c for c in s.components if c.component_id == "gerp_recommendation_gap")
    assert part.value is None and part.contribution == 0 and part.rationale.startswith("MISSING")


def test_penalties_apply_conservatively_when_inputs_are_missing(config: OpportunityConfig) -> None:
    metrics = _clean_metrics()
    del metrics["quality.min_sample_n"]
    s = score(_components(), metrics, config.scoring)
    low_sample = next(p for p in s.penalties if p.penalty_id == "low_sample")
    assert low_sample.applied and low_sample.observed is None and "NOT_COLLECTED" in low_sample.reason
    assert s.total == pytest.approx(0.8 - low_sample.amount)


def test_priority_thresholds(config: OpportunityConfig) -> None:
    t = config.scoring.priority_thresholds
    assert score(_components(t.high), _clean_metrics(), config.scoring).priority == "HIGH"
    assert score(_components(t.medium), _clean_metrics(), config.scoring).priority == "MEDIUM"
    assert score(_components(t.medium - 0.01), _clean_metrics(), config.scoring).priority == "LOW"
