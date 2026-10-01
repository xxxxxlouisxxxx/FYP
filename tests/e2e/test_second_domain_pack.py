"""Spec 2.2: a second domain pack runs on the unchanged platform runtime and product services."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hop.bootstrap import App, build_app
from hop.platform.common_contracts import RunStatus
from hop.platform.domain_registry import load_domain_pack
from hop.platform.evaluation import EvaluationHarness
from hop.products.opportunity_intelligence.config import load_opportunity_config
from hop.products.opportunity_intelligence.evaluation import run_suites
from hop.products.opportunity_intelligence.gap_detection import run_rule_tests
from hop.products.opportunity_intelligence.pipeline import WORKFLOW_NAME, WORKFLOW_VERSION, start_discovery
from tests.conftest import REPO_ROOT, Discovery, hk_request, make_settings

PACK_ID = "outdoor-apparel"
PACK_DIR = REPO_ROOT / "domain_packs" / "outdoor_apparel"
PACK_TERMS = re.compile(r"outdoor[-_ ]apparel|rain jacket|merino|Arc'teryx|Patagonia|Uniqlo", re.IGNORECASE)


def _app(data_dir: Path, pack_id: str) -> App:
    return build_app(make_settings(data_dir), pack_id=pack_id, sleep=lambda _s: None)


def test_second_pack_is_pure_configuration() -> None:
    files = [p for p in PACK_DIR.rglob("*") if p.is_file()]
    assert files and all(p.suffix in {".yaml", ".json"} for p in files)
    code = [p for p in (REPO_ROOT / "hop").rglob("*.py") if PACK_TERMS.search(p.read_text(encoding="utf-8"))]
    assert code == [], f"platform/product code must not know about the {PACK_ID} pack: {code}"


def test_second_pack_validates_and_its_rules_and_golden_sets_pass(tmp_path: Path) -> None:
    pack = load_domain_pack(REPO_ROOT / "domain_packs", PACK_ID)
    config = load_opportunity_config(pack)
    assert all(run_rule_tests(rs).passed for rs in config.rule_sets.values())
    app = _app(tmp_path, PACK_ID)
    p = app.platform
    results = run_suites(
        EvaluationHarness(p.store, p.telemetry, p.audit), p.gateway, app.pack, app.config, app.resolver, None
    )
    assert {r.suite_id for r in results} == {"gerp-recommendation-v1", "entity-resolution-v1"}
    for r in results:
        assert r.passed, (r.suite_id, r.checks, r.failures[:3])


def test_second_pack_runs_end_to_end_on_the_same_runtime(discovery: Discovery, tmp_path: Path) -> None:
    app = _app(tmp_path, PACK_ID)
    run = start_discovery(app.discovery_deps(), hk_request(domain_pack=PACK_ID), force_new=True)
    assert run.status == RunStatus.SUCCEEDED, run.error
    assert (run.workflow, run.workflow_version) == (WORKFLOW_NAME, WORKFLOW_VERSION)
    assert (discovery.run.workflow, discovery.run.workflow_version) == (WORKFLOW_NAME, WORKFLOW_VERSION)
    assert [s.name for s in run.steps] == [s.name for s in discovery.run.steps]

    cards = app.repo.cards(run_id=run.run_id)
    assert cards, "the second pack produced no Opportunity Cards"
    assert {c.domain_pack for c in cards} == {PACK_ID}
    assert {(c.rule_version, c.score_version) for c in cards} == {("1.0.0", "score-v0.1.0")}
    assert all(app.platform.evidence.verify_lineage(e).valid for c in cards for e in c.supporting_evidence_ids)
    assert app.platform.audit.verify_chain()[0]


def test_both_packs_share_one_platform_store(tmp_path: Path) -> None:
    footwear = _app(tmp_path, "sports-footwear")
    apparel = _app(tmp_path, PACK_ID)
    first = start_discovery(footwear.discovery_deps(), hk_request(), force_new=True)
    second = start_discovery(apparel.discovery_deps(), hk_request(domain_pack=PACK_ID), force_new=True)
    assert first.status == second.status == RunStatus.SUCCEEDED
    packs = {c.domain_pack for c in apparel.repo.cards()}
    assert packs == {"sports-footwear", PACK_ID}
    assert apparel.platform.audit.verify_chain()[0]


@pytest.mark.parametrize("pack_id", ["sports-footwear", PACK_ID])
def test_markets_are_scoped_to_their_pack(tmp_path: Path, pack_id: str) -> None:
    app = _app(tmp_path, pack_id)
    with pytest.raises(KeyError, match=f"market ZZ not configured in domain pack {pack_id}"):
        start_discovery(app.discovery_deps(), hk_request(domain_pack=pack_id, market="ZZ"), force_new=True)
