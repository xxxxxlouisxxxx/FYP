"""Collection Request, Observation and Collection Run contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from hop.platform.common_contracts.base import Contract, canonical_json, new_id, sha256_hex, utcnow
from hop.platform.common_contracts.missingness import ValueState


class SignalFamily(StrEnum):
    DEMAND = "demand"
    SERP = "serp"
    GERP = "gerp"


class Device(StrEnum):
    MOBILE = "mobile"
    DESKTOP = "desktop"


class CollectionRequest(Contract):
    """What an analyst asks the platform to collect. Validated before any spend."""

    schema_version: Literal["collection_request_v1"] = "collection_request_v1"
    request_id: str = Field(default_factory=lambda: new_id("req"))
    domain_pack: str
    market: str = Field(pattern=r"^[A-Z]{2}$")
    tier: str = Field(pattern=r"^[A-Z]$")
    language: str | None = None
    device: Device | None = None
    signal_families: list[SignalFamily] = Field(
        default_factory=lambda: [SignalFamily.DEMAND, SignalFamily.SERP, SignalFamily.GERP]
    )
    gerp_repeats: int | None = Field(default=None, ge=1, le=10)
    serp_provider: str = "auto"
    model_provider: str = "auto"
    budget_usd: float | None = Field(default=None, gt=0)
    budget_approved_by: str | None = None
    decision_question: str | None = None
    requested_by: str = "cli"
    collection_window: str = Field(
        default_factory=lambda: utcnow().strftime("%Y-%m-%d"),
        description="Idempotency window; the same request in the same window maps to the same run",
    )

    def idempotency_key(self) -> str:
        body = self.model_dump(mode="json", exclude={"request_id", "requested_by", "decision_question"})
        return sha256_hex(canonical_json(body))


class Observation(Contract):
    """One provider or model observation. Raw bytes live in the object store, referenced by hash."""

    schema_version: Literal["observation_v1"] = "observation_v1"
    observation_id: str
    run_id: str
    signal_family: SignalFamily
    provider: str
    endpoint: str
    market: str
    locale: str
    language: str
    device: Device
    query_id: str
    query_text: str
    need_id: str
    prompt_id: str | None = None
    prompt_version: str | None = None
    model_id: str | None = None
    repeat_index: int = 0
    observed_at: datetime
    status: ValueState
    raw_artifact_uri: str | None = None
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    parser_version: str | None = None
    provider_task_id: str | None = None
    cost_usd: float = 0.0
    simulated: bool = False
    retry_count: int = 0
    trace_id: str | None = None
    error: str | None = None
    quality_flags: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)


class RunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    KILLED = "KILLED"
    REJECTED_BUDGET = "REJECTED_BUDGET"


class StepStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class StepState(Contract):
    name: str
    status: StepStatus = StepStatus.PENDING
    attempts: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: float | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    failure_class: str | None = None
    restored_from_checkpoint: bool = False


class CostLine(Contract):
    item: str
    provider: str
    units: float
    unit: str
    unit_cost_usd: float
    total_usd: float
    simulated: bool = False


class CostEstimate(Contract):
    lines: list[CostLine]
    total_usd: float
    budget_usd: float
    within_budget: bool
    currency: Literal["USD"] = "USD"


class CollectionRun(Contract):
    schema_version: Literal["collection_run_v1"] = "collection_run_v1"
    run_id: str
    idempotency_key: str
    workflow: str
    workflow_version: str
    status: RunStatus
    tenant_id: str
    request: dict[str, Any]
    cost_estimate: CostEstimate | None = None
    budget_usd: float
    actual_cost_usd: float = 0.0
    trace_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    steps: list[StepState] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    failure_class: str | None = None
    resumed_count: int = 0
