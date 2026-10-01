"""Gap Candidate and Opportunity Card contracts (the product's first published contracts)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from hop.platform.common_contracts import Contract, DataQualityStatus, MetricValue, SignalFamily, utcnow


class AdmissionOutcome(StrEnum):
    PENDING = "PENDING"
    ADMITTED = "ADMITTED"
    NOT_ADMITTED = "NOT_ADMITTED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"


class CounterEvidenceStatus(StrEnum):
    NOT_RUN = "NOT_RUN"
    COMPLETED = "COMPLETED"
    UNAVAILABLE = "UNAVAILABLE"


class GateResult(Contract):
    gate_id: str
    label: str
    passed: bool
    severity: Literal["critical", "standard"] = "standard"
    detail: str


class ScoreComponent(Contract):
    component_id: str
    weight: float
    value: float | None
    contribution: float
    source: str
    rationale: str


class RiskPenalty(Contract):
    penalty_id: str
    label: str
    amount: float
    applied: bool
    observed: float | None
    reason: str


class ScoreBreakdown(Contract):
    score_version: str
    formula: str
    components: list[ScoreComponent]
    penalties: list[RiskPenalty]
    gross: float
    total_penalty: float
    total: float = Field(ge=0, le=1)
    priority: Literal["HIGH", "MEDIUM", "LOW"]
    sensitivity: dict[str, float] = Field(default_factory=dict, description="score change if each weight +0.05")


class GapCandidate(Contract):
    schema_version: Literal["gap_candidate_v1"] = "gap_candidate_v1"
    candidate_id: str
    run_id: str
    trace_id: str | None = None
    domain_pack: str
    domain_pack_version: str
    rule_set_id: str
    rule_id: str
    rule_version: str
    gap_family: str
    market: str
    need_id: str
    need_label: str
    brand_id: str | None = None
    attribute_ids: list[str] = Field(default_factory=list)
    signal_families: list[SignalFamily]
    observed_signal_families: list[SignalFamily] = Field(default_factory=list)
    metrics: dict[str, MetricValue] = Field(default_factory=dict)
    condition_trace: list[dict] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    counter_evidence_ids: list[str] = Field(default_factory=list)
    counter_evidence_status: CounterEvidenceStatus = CounterEvidenceStatus.NOT_RUN
    counter_evidence_strength: float | None = None
    counter_evidence_notes: list[str] = Field(default_factory=list)
    entity_ambiguity_rate: float | None = None
    freshness_days: float | None = None
    freshness_policy_days: int
    data_quality_status: DataQualityStatus = DataQualityStatus.PASSED
    gate_results: list[GateResult] = Field(default_factory=list)
    admission: AdmissionOutcome = AdmissionOutcome.PENDING
    admission_reason: str | None = None
    score: ScoreBreakdown | None = None
    score_version: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class OpportunityStatus(StrEnum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    WATCHLIST = "WATCHLIST"
    REJECTED = "REJECTED"


class StatementKind(StrEnum):
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"
    LIMITATION = "LIMITATION"


class Statement(Contract):
    kind: StatementKind
    text: str
    evidence_ids: list[str] = Field(default_factory=list)


class Explanation(Contract):
    summary: str
    generator: Literal["template", "model_gateway"]
    model_id: str | None = None
    prompt_id: str | None = None
    prompt_version: str | None = None
    cited_evidence_ids: list[str] = Field(default_factory=list)
    validated: bool
    validation_notes: list[str] = Field(default_factory=list)


class OpportunityCard(Contract):
    schema_version: Literal["opportunity_card_v1"] = "opportunity_card_v1"
    card_id: str
    candidate_id: str
    run_id: str
    trace_id: str | None = None
    title: str
    market: str
    need_id: str
    need_label: str
    brand_id: str | None = None
    attribute_ids: list[str] = Field(default_factory=list)
    gap_family: str
    status: OpportunityStatus = OpportunityStatus.DRAFT
    priority: Literal["HIGH", "MEDIUM", "LOW"]
    score: ScoreBreakdown
    confidence_label: Literal["high", "moderate", "low", "exploratory"]
    evidence_confidence: float = Field(ge=0, le=1)
    sample_summary: dict[str, MetricValue] = Field(default_factory=dict)
    observed: list[Statement] = Field(default_factory=list)
    inferred: list[Statement] = Field(default_factory=list)
    unknowns: list[Statement] = Field(default_factory=list)
    limitations: list[Statement] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(min_length=1)
    counter_evidence_ids: list[str] = Field(default_factory=list)
    counter_evidence_status: CounterEvidenceStatus
    explanation: Explanation
    next_validation_action: str
    requires_human_approval: bool = True
    required_approver_role: str = "analyst"
    owner: str | None = None
    approver: str | None = None
    proposed_action: str | None = None
    rule_set_id: str
    rule_id: str
    rule_version: str
    score_version: str
    domain_pack: str
    domain_pack_version: str
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    model_ids: list[str] = Field(default_factory=list)
    lineage_verified: bool
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
