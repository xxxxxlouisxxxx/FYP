"""Governed export of Opportunity Cards (JSON / CSV) with lineage, versions and review status."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Literal

from hop.platform.common_contracts import ActorType
from hop.platform.services import PlatformServices
from hop.products.opportunity_intelligence.contracts import OpportunityCard

CAPABILITY_ID = "opportunity.exporter"
CSV_FIELDS = (
    "card_id", "status", "priority", "score", "confidence_label", "market", "need_id", "brand_id", "gap_family",
    "title", "owner", "approver", "rule_id", "rule_version", "score_version", "domain_pack_version",
    "supporting_evidence", "counter_evidence", "lineage_verified", "run_id", "trace_id",
)  # fmt: skip


def render(cards: list[OpportunityCard], fmt: Literal["json", "csv"]) -> bytes:
    if fmt == "json":
        return json.dumps([c.model_dump(mode="json") for c in cards], indent=2, ensure_ascii=False).encode()
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for c in cards:
        writer.writerow({
            "card_id": c.card_id, "status": c.status.value, "priority": c.priority, "score": c.score.total,
            "confidence_label": c.confidence_label, "market": c.market, "need_id": c.need_id,
            "brand_id": c.brand_id or "", "gap_family": c.gap_family, "title": c.title, "owner": c.owner or "",
            "approver": c.approver or "", "rule_id": c.rule_id, "rule_version": c.rule_version,
            "score_version": c.score_version, "domain_pack_version": c.domain_pack_version,
            "supporting_evidence": len(c.supporting_evidence_ids), "counter_evidence": len(c.counter_evidence_ids),
            "lineage_verified": c.lineage_verified, "run_id": c.run_id, "trace_id": c.trace_id or "",
        })  # fmt: skip
    return buf.getvalue().encode()


def export_cards(
    platform: PlatformServices,
    cards: list[OpportunityCard],
    *,
    fmt: Literal["json", "csv"],
    actor: str,
    out: Path | None = None,
) -> tuple[str, bytes]:
    """Writes the export to the object store (write-once) and optionally to a local file. Returns (uri, bytes)."""
    platform.policy.enforce_tool(CAPABILITY_ID, "object_store.export_write")
    data = render(cards, fmt)
    with platform.telemetry.span("Opportunity export", {"export.format": fmt, "export.cards": len(cards)}):
        artifact = platform.evidence.persist_raw(
            data,
            run_id=None,
            namespace=f"exports/{fmt}",
            content_type="text/csv" if fmt == "csv" else "application/json",
        )
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
    platform.audit.record(
        actor=actor, actor_type=ActorType.HUMAN, action="opportunity.export", resource_type="export",
        resource_id=artifact.uri, details={"format": fmt, "cards": len(cards), "sha256": artifact.sha256},
    )  # fmt: skip
    return artifact.uri, data
