"""JSON Schema export for every published contract (platform and product)."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from hop.platform.capability_registry import CapabilityManifest
from hop.platform.common_contracts import (
    AgentRun,
    AuditEvent,
    CollectionRequest,
    CollectionRun,
    EvaluationRun,
    EvidenceItem,
    Observation,
    PolicyDecision,
    ReviewDecision,
)
from hop.products.opportunity_intelligence.contracts import GapCandidate, OpportunityCard

CONTRACTS: dict[str, type[BaseModel]] = {
    "collection_request_v1": CollectionRequest,
    "observation_v1": Observation,
    "evidence_item_v1": EvidenceItem,
    "gap_candidate_v1": GapCandidate,
    "opportunity_card_v1": OpportunityCard,
    "review_decision_v1": ReviewDecision,
    "audit_event_v1": AuditEvent,
    "agent_run_v1": AgentRun,
    "collection_run_v1": CollectionRun,
    "policy_decision_v1": PolicyDecision,
    "evaluation_run_v1": EvaluationRun,
    "capability_manifest_v1": CapabilityManifest,
}


def schema_documents() -> dict[str, str]:
    return {
        f"{name}.schema.json": json.dumps(model.model_json_schema(), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n"
        for name, model in CONTRACTS.items()
    }


def export_schemas(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for filename, text in schema_documents().items():
        path = out_dir / filename
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written
