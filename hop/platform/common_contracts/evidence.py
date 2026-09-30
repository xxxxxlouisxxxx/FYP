"""Evidence Item contract (spec section 5.3). Immutable; corrections create a new version."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from hop.platform.common_contracts.base import (
    SHA256_PATTERN,
    FrozenContract,
    canonical_json,
    sha256_hex,
    utcnow,
)
from hop.platform.common_contracts.collection import Device


class EvidenceType(StrEnum):
    DEMAND_SIGNAL = "DEMAND_SIGNAL"
    SERP_RESULT = "SERP_RESULT"
    SERP_FEATURE = "SERP_FEATURE"
    GERP_ANSWER = "GERP_ANSWER"
    GERP_PRIMARY_RECOMMENDATION = "GERP_PRIMARY_RECOMMENDATION"
    GERP_SUPPORTING_RECOMMENDATION = "GERP_SUPPORTING_RECOMMENDATION"
    GERP_MENTION = "GERP_MENTION"
    GERP_EXCLUSION = "GERP_EXCLUSION"
    GERP_CITATION = "GERP_CITATION"
    COUNTER_EVIDENCE = "COUNTER_EVIDENCE"


class DataQualityStatus(StrEnum):
    PASSED = "PASSED"
    WARNING = "WARNING"
    FAILED_NON_CRITICAL = "FAILED_NON_CRITICAL"
    FAILED_CRITICAL = "FAILED_CRITICAL"
    QUARANTINED = "QUARANTINED"


class AccessClassification(StrEnum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"


class RetentionClass(StrEnum):
    RAW_PROVIDER_90D = "RAW_PROVIDER_90D"
    MODEL_OUTPUT_1Y = "MODEL_OUTPUT_1Y"
    DERIVED_2Y = "DERIVED_2Y"
    AUDIT_7Y = "AUDIT_7Y"


class SourceSpan(FrozenContract):
    field: str = Field(description="JSON path of the text inside the parsed payload")
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    text: str


class CostAttribution(FrozenContract):
    usd: float = Field(ge=0)
    unit: str
    simulated: bool = False


class EvidenceItem(FrozenContract):
    schema_version: Literal["evidence_item_v1"] = "evidence_item_v1"
    evidence_id: str
    version: int = Field(default=1, ge=1)
    supersedes_version: int | None = None
    correction_reason: str | None = None
    evidence_type: EvidenceType
    source_provider: str
    source_endpoint: str
    market: str
    locale: str
    language: str
    device: Device
    query_id: str | None = None
    prompt_id: str | None = None
    observed_at: datetime
    raw_payload_uri: str
    content_hash: str = Field(pattern=SHA256_PATTERN, description="SHA-256 of the raw payload bytes")
    parser_version: str
    payload_schema_version: str
    model_id: str | None = None
    prompt_version: str | None = None
    extracted_claim: str
    source_span: SourceSpan | None = None
    entity_refs: tuple[str, ...] = ()
    data_quality_status: DataQualityStatus = DataQualityStatus.PASSED
    quality_flags: tuple[str, ...] = ()
    access_classification: AccessClassification = AccessClassification.INTERNAL
    retention_class: RetentionClass = RetentionClass.RAW_PROVIDER_90D
    cost_attribution: CostAttribution
    trace_id: str | None = None
    run_id: str
    observation_id: str | None = None
    need_id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    untrusted_content: bool = True
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def key(self) -> str:
        return f"{self.evidence_id}@v{self.version}"

    def record_hash(self) -> str:
        """Hash of the evidence record itself (excluding creation time) for tamper detection."""
        return sha256_hex(canonical_json(self.model_dump(mode="json", exclude={"created_at"})))
