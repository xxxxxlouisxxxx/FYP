"""Spec 2.2: a new market is onboarded by configuration and fixtures only - no code changes."""

from __future__ import annotations

import filecmp
import hashlib
import importlib.util
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hop.cli import main as cli
from hop.platform.common_contracts import RunStatus
from hop.products.opportunity_intelligence.pipeline import start_discovery
from tests.conftest import REPO_ROOT, hk_request, make_app, point_env_at

spec = importlib.util.spec_from_file_location("hop_fixtures", REPO_ROOT / "scripts" / "generate_sandbox_fixtures.py")
assert spec and spec.loader
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)

MY_PROFILE = {
    "name": "Malaysia",
    "loc": 2458,
    "se": "google.com.my",
    "retail": ["www.zalora.com.my", "www.lazada.com.my", "www.shopee.com.my", "www.jdsports.my"],
    "forum": ["forum.lowyat.net", "www.reddit.com"],
    "news": "www.thestar.com.my",
}
MY_SCENARIOS = {
    "wide_toe_box": dict(volume=1300, yoy=0.18, supply=2, recs=1, cite="high", stable=True),
    "humid_breathable": dict(volume=2400, yoy=0.25, supply=2, recs=1, cite="high", stable=True),
    "plantar_fasciitis": dict(volume=900, yoy=0.05, supply=6, recs=3, cite="high", stable=True),
    "carbon_plate_racing": dict(volume=1200, yoy=0.04, supply=8, recs=3, cite="high", stable=True),
    "heavy_runner": dict(volume=600, yoy=0.07, supply=5, recs=3, cite="high", stable=True),
    "trail_waterproof": dict(volume=500, yoy=0.01, supply=6, recs=3, cite="high", stable=True),
    "vegan_sustainable": dict(volume=210, yoy=0.12, supply=1, recs=1, cite="high", stable=True),
    "budget_beginner": dict(volume=None, yoy=0.0, supply=3, recs=3, cite="high", stable=True),
    "flat_feet_stability": dict(volume=800, yoy=0.03, supply=7, recs=3, cite="high", stable=True),
}


def _tree_digest(root: Path, pattern: str) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob(pattern)):
        if "__pycache__" not in p.parts:
            h.update(str(p.relative_to(root)).encode() + b"\0" + p.read_bytes())
    return h.hexdigest()


def _changed_files(before: Path, after: Path) -> set[str]:
    changed: set[str] = set()
    for p in after.rglob("*"):
        if p.is_file():
            rel = p.relative_to(after)
            if not (before / rel).exists() or not filecmp.cmp(before / rel, p, shallow=False):
                changed.add(str(rel))
    return changed


@pytest.mark.parametrize("market", ["SG", "US"])
def test_configured_markets_produce_their_own_cards(tmp_path: Path, market: str) -> None:
    app = make_app(tmp_path)
    run = start_discovery(app.discovery_deps(), hk_request(market=market), force_new=True)
    assert run.status == RunStatus.SUCCEEDED, run.error
    cards = app.repo.cards(run_id=run.run_id)
    assert cards, f"{market} sandbox run produced no cards"
    assert {c.market for c in cards} == {market}


def test_new_market_is_onboarded_by_config_and_fixtures_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    code_before = _tree_digest(REPO_ROOT / "hop", "*.py")
    packs = tmp_path / "domain_packs"
    shutil.copytree(REPO_ROOT / "domain_packs", packs)
    data_dir = tmp_path / "data"
    point_env_at(data_dir, monkeypatch)
    monkeypatch.setenv("HOP_DOMAIN_PACKS_DIR", str(packs))
    cli.get_app.cache_clear()
    runner = CliRunner()
    try:
        added = runner.invoke(cli.app, [
            "market", "add", "--code", "MY", "--name", "Malaysia", "--locale", "en=en-MY=en",
            "--location-code", "2458", "--currency", "MYR", "--timezone", "Asia/Kuala_Lumpur",
            "--reference-volume", "3000",
        ])  # fmt: skip
        assert added.exit_code == 0, added.output
        fixtures.write_market(packs / "sports_footwear" / "sandbox", "MY", MY_PROFILE, MY_SCENARIOS)

        validated = runner.invoke(cli.app, ["domain", "validate", "sports-footwear"])
        assert validated.exit_code == 0, validated.output

        ran = runner.invoke(cli.app, ["collection", "run", "--market", "MY", "--tier", "A"])
        assert ran.exit_code == 0, ran.output
        assert "SUCCEEDED" in ran.output
    finally:
        cli.get_app.cache_clear()

    app = make_app(data_dir, domain_packs_dir=packs)
    runs = app.platform.runtime.list_runs()
    assert [r.status for r in runs] == [RunStatus.SUCCEEDED]
    cards = app.repo.cards(run_id=runs[0].run_id)
    assert cards and {c.market for c in cards} == {"MY"}

    changed = _changed_files(REPO_ROOT / "domain_packs", packs)
    assert "sports_footwear/markets/markets.yaml" in changed
    assert all(
        f == "sports_footwear/markets/markets.yaml" or f.startswith("sports_footwear/sandbox/MY/") for f in changed
    )
    assert _tree_digest(REPO_ROOT / "hop", "*.py") == code_before
