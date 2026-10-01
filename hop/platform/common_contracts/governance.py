"""Governance contracts: review decisions, audit events, agent runs, policy decisions, evaluation runs."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from hop.platform.common_contracts.base import SHA256_PATTERN, Contract, FrozenContract, new_id, utcnow


class ActorType(StrEnum):
    HUMAN = "HUMAN"
    SYSTEM = "SYSTEM"
    AGENT = "AGENT"


class ReviewAction(StrEnum):
    SUBMIT_FOR_REVIEW = "SUBMIT_FOR_REVIEW"
    APPROVE = "APPROVE"
    WATCHLIST = "WATCHLIST"
    REJECT = "REJECT"
    REOPEN = "REOPEN"


class ReviewDecision(FrozenContract):
    schema_version: Literal["review_decision_v1"] = "review_decision_v1"
    decision_id: str = Field(default_factory=lambda: new_id("rev"))
    resource_type: str = "opportunity_card"
    resource_id: str
    action: ReviewAction
    from_status: str
    to_status: str
    reviewer: str = Field(min_length=2)
    reviewer_role: str
    rationale: str | None = None
    owner_assigned: str | None = None
    proposed_action: str | None = None
    decided_at: datetime = Field(default_factory=utcnow)
    trace_id: str | None = None


class AuditEvent(FrozenContract):
    """Append-only, hash-chained audit record."""

    schema_version: Literal["audit_event_v1"] = "audit_event_v1"
    event_id: str = Field(default_factory=lambda: new_id("aud"))
    occurred_at: datetime = Field(default_factory=utcnow)
    actor: str
    actor_type: ActorType
    action: str
    resource_type: str
    resource_id: str
    outcome: Literal["SUCCESS", "DENIED", "FAILURE"] = "SUCCESS"
    details: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None
    tenant_id: str = "hktdc"
    prev_event_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    event_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)


class AgentRunStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    ABSTAINED = "ABSTAINED"
    FAILED = "FAILED"
    DENIED = "DENIED"


class AgentRun(Contract):
    schema_version: Literal["agent_run_v1"] = "agent_run_v1"
    agent_run_id: str = Field(default_factory=lambda: new_id("agr"))
    run_id: str | None = None
    capability_id: str
    capability_version: str
    purpose: str
    status: AgentRunStatus
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    steps: int = 0
    max_steps: int
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    simulated: bool = False
    model_id: str | None = None
    provider: str | None = None
    prompt_id: str | None = None
    prompt_version: str | None = None
    request_hash: str | None = None
    response_hash: str | None = None
    payload_uri: str | None = None
    abstention_reason: str | None = None
    retry_count: int = 0
    trace_id: str | None = None
    span_id: str | None = None


class PolicyDecision(Contract):
    schema_version: Literal["policy_decision_v1"] = "policy_decision_v1"
    decision_id: str = Field(default_factory=lambda: new_id("pol"))
    subject: str
    action: str
    resource: str
    allowed: bool
    reason: str
    policy_version: str = "policy-v1.0.0"
    run_id: str | None = None
    trace_id: str | None = None
    decided_at: datetime = Field(default_factory=utcnow)


class EvaluationRun(Contract):
    schema_version: Literal["evaluation_run_v1"] = "evaluation_run_v1"
    evaluation_run_id: str = Field(default_factory=lambda: new_id("evr"))
    suite_id: str
    suite_version: str
    dataset_version: str
    partition: str
    subject: dict[str, str]
    metrics: dict[str, float | None]
    thresholds: dict[str, dict[str, float]]
    checks: list[dict[str, Any]]
    passed: bool
    n_cases: int
    failures: list[dict[str, Any]] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    trace_id: str | None = None
