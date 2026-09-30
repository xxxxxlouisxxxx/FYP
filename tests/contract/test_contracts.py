from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from hop.platform.capability_registry import CapabilityManifest
from hop.platform.common_contracts import CollectionRequest, EvidenceItem
from hop.schemas import CONTRACTS, schema_documents
from tests.conftest import REPO_ROOT, Discovery

SCHEMA_DIR = REPO_ROOT / "docs" / "reference" / "schemas"


def test_published_schemas_match_code() -> None:
    """Contract changes must be deliberate: re-run `hop schema export` and commit the diff."""
    documents = schema_documents()
    on_disk = {p.name for p in SCHEMA_DIR.glob("*.schema.json")}
    assert on_disk == set(documents)
    for name, text in documents.items():
        assert json.loads((SCHEMA_DIR / name).read_text()) == json.loads(text), f"schema drift in {name}"


@pytest.mark.parametrize("name", sorted(CONTRACTS))
def test_schema_is_versioned_object(name: str) -> None:
    schema = CONTRACTS[name].model_json_schema()
    assert schema["type"] == "object" and schema["properties"]


def test_collection_request_validation() -> None:
    with pytest.raises(ValidationError):
        CollectionRequest(domain_pack="sports-footwear", market="hk", tier="A")
    with pytest.raises(ValidationError):
        CollectionRequest(domain_pack="sports-footwear", market="HK", tier="A", budget_usd=0)
    a = CollectionRequest(domain_pack="sports-footwear", market="HK", tier="A", requested_by="a")
    b = CollectionRequest(domain_pack="sports-footwear", market="HK", tier="A", requested_by="b")
    assert a.idempotency_key() == b.idempotency_key()
    assert (
        a.idempotency_key() != CollectionRequest(domain_pack="sports-footwear", market="SG", tier="A").idempotency_key()
    )


def test_contracts_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        CollectionRequest(domain_pack="sports-footwear", market="HK", tier="A", surprise=True)


def test_evidence_items_are_immutable_and_hash_checked(discovery: Discovery) -> None:
    item = discovery.app.platform.evidence.search(run_id=discovery.run.run_id, limit=1)[0]
    with pytest.raises(ValidationError):
        item.extracted_claim = "tampered"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        EvidenceItem.model_validate({**item.model_dump(), "content_hash": "not-a-hash"})
    assert EvidenceItem.model_validate_json(item.model_dump_json()) == item


@pytest.mark.parametrize(
    "path",
    sorted(
        [
            *(REPO_ROOT / "hop" / "platform" / "capability_registry" / "manifests").glob("*.yaml"),
            *(REPO_ROOT / "hop" / "products" / "opportunity_intelligence" / "capabilities").glob("*.yaml"),
        ]
    ),
    ids=lambda p: p.stem,
)
def test_capability_manifests_validate(path: Path) -> None:
    manifest = CapabilityManifest.model_validate(yaml.safe_load(path.read_text()))
    assert manifest.capability_id == path.stem
    assert manifest.owner and manifest.purpose


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_platform_core_is_domain_agnostic() -> None:
    offenders = []
    for path in (REPO_ROOT / "hop" / "platform").rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        bad = {m for m in _imports(path) if m.startswith(("hop.products", "hop.bootstrap", "domain_packs"))}
        if bad:
            offenders.append(f"{path}: imports {sorted(bad)}")
        for word in ("footwear", "running shoe", "sneaker"):
            if word in text:
                offenders.append(f"{path}: mentions '{word}'")
    assert offenders == []


def test_no_top_level_platform_package_shadows_stdlib() -> None:
    assert not (REPO_ROOT / "platform" / "__init__.py").exists()
    assert not (REPO_ROOT / "platform.py").exists()
