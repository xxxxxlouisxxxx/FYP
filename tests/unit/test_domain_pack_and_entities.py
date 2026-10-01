from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from hop.platform.domain_registry import DomainPackError, MarketConfig, add_market, load_domain_pack
from hop.platform.entity_resolution import EntityResolver, ResolutionStatus
from tests.conftest import REPO_ROOT

PACKS = REPO_ROOT / "domain_packs"


@pytest.fixture(scope="module")
def pack():  # noqa: ANN201
    return load_domain_pack(PACKS, "sports-footwear")


@pytest.fixture
def pack_copy(tmp_path: Path) -> Path:
    shutil.copytree(PACKS / "sports_footwear", tmp_path / "sports_footwear", ignore=shutil.ignore_patterns("sandbox"))
    return tmp_path


def test_packaged_pack_validates(pack) -> None:  # noqa: ANN001
    assert pack.pack_id == "sports-footwear"
    assert {"HK", "SG"} <= set(pack.markets)
    assert pack.queries_for("HK", "A", None)
    assert pack.prompt("opportunity_explanation").untrusted_variables is not None


def test_invalid_pack_reports_every_error(pack_copy: Path) -> None:
    brands = pack_copy / "sports_footwear" / "brands" / "brands.yaml"
    data = yaml.safe_load(brands.read_text())
    data["entities"].append(dict(data["entities"][0]))
    brands.write_text(yaml.safe_dump(data))
    with pytest.raises(DomainPackError) as exc:
        load_domain_pack(pack_copy, "sports-footwear")
    assert any("duplicate" in e for e in exc.value.errors)


def test_unquoted_yaml_boolean_is_rejected(pack_copy: Path) -> None:
    brands = pack_copy / "sports_footwear" / "brands" / "brands.yaml"
    brands.write_text(brands.read_text().replace('name: "On"', "name: On"))
    with pytest.raises(DomainPackError):
        load_domain_pack(pack_copy, "sports-footwear")


def test_add_market_by_configuration(pack_copy: Path, pack) -> None:  # noqa: ANN001
    hk = pack.market("HK").model_dump()
    tw = MarketConfig.model_validate({**hk, "code": "TW", "name": "Taiwan", "provider_location_code": 2158})
    add_market(pack_copy, "sports-footwear", tw)
    assert "TW" in load_domain_pack(pack_copy, "sports-footwear").markets
    with pytest.raises(DomainPackError):
        add_market(pack_copy, "sports-footwear", tw)


def test_ambiguous_brand_needs_context(pack) -> None:  # noqa: ANN001
    resolver = EntityResolver(pack.entities)
    [hit] = [h for h in resolver.scan("Try the On Cloudmonster for long runs.") if h.surface == "On"]
    assert hit.resolution.status == ResolutionStatus.RESOLVED and hit.resolution.entity_id == "on_running"
    hits = [h for h in resolver.scan("Put your shoes On and go.") if h.surface == "On"]
    assert hits and hits[0].resolution.status == ResolutionStatus.AMBIGUOUS
    assert not [h for h in resolver.scan("turn it on") if h.resolution.entity_id == "on_running"]


def test_exact_alias_resolves(pack) -> None:  # noqa: ANN001
    resolver = EntityResolver(pack.entities)
    res = resolver.resolve("Saucony")
    assert res.status == ResolutionStatus.RESOLVED and res.confidence == 1.0
    assert resolver.resolve("NotABrand").status == ResolutionStatus.UNRESOLVED
