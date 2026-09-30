"""Tools that bounded product agents may call through ``AgentSession`` (deny-by-default per manifest)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from hop.platform.common_contracts import EvidenceType
from hop.platform.domain_registry import DomainPack
from hop.platform.evidence_service import EvidenceService
from hop.platform.policy_engine.tools import ToolRegistry


class EvidenceSearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    need_id: str | None = None
    evidence_types: list[EvidenceType] = Field(default_factory=list)
    attribute_filter: dict[str, Any] = Field(default_factory=dict)
    include_quarantined: bool = False
    limit: int = Field(default=50, ge=1, le=200)


class TaxonomyLookupArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    need_id: str


def build_tool_registry(evidence: EvidenceService, pack: DomainPack) -> ToolRegistry:
    tools = ToolRegistry()

    def evidence_search(args: EvidenceSearchArgs) -> list[Any]:
        return evidence.search(
            run_id=args.run_id,
            need_id=args.need_id,
            evidence_types=args.evidence_types or None,
            attribute_filter=args.attribute_filter or None,
            exclude_quarantined=not args.include_quarantined,
            limit=args.limit,
        )

    def taxonomy_lookup(args: TaxonomyLookupArgs) -> dict[str, Any]:
        need = pack.needs.get(args.need_id)
        if need is None:
            return {"found": False}
        siblings = sorted(
            n.need_id for n in pack.needs.values() if n.parent == need.parent and n.need_id != need.need_id
        )
        return {"found": True, "need": need.model_dump(), "siblings": siblings}

    tools.register("evidence.search", evidence_search, EvidenceSearchArgs, "Search acquired evidence for a run")
    tools.register("taxonomy.lookup", taxonomy_lookup, TaxonomyLookupArgs, "Look up a consumer need in the taxonomy")
    return tools
