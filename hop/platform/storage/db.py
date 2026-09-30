"""Relational system of record. SQLite by default, PostgreSQL via ``DATABASE_URL``.

Tables keep a few indexed columns for filtering and the full contract as JSON ``body`` so that
contract evolution does not require schema migrations in the walking skeleton.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from hop.platform.common_contracts.base import utcnow


class ImmutableRecordError(RuntimeError):
    """Raised on any attempt to update or delete an append-only record."""


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, datetime: DateTime(timezone=True)}


class RunRow(Base):
    __tablename__ = "runs"
    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    workflow: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), index=True)
    market: Mapped[str | None] = mapped_column(String(8), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    body: Mapped[dict[str, Any]]


class CheckpointRow(Base):
    __tablename__ = "checkpoints"
    __table_args__ = (UniqueConstraint("run_id", "step"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    step: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    output: Mapped[dict[str, Any]]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class DeadLetterRow(Base):
    __tablename__ = "dead_letters"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    step: Mapped[str] = mapped_column(String(64))
    failure_class: Mapped[str] = mapped_column(String(64))
    error: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ObservationRow(Base):
    __tablename__ = "observations"
    observation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    signal_family: Mapped[str] = mapped_column(String(16), index=True)
    market: Mapped[str] = mapped_column(String(8))
    query_id: Mapped[str] = mapped_column(String(128))
    need_id: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32))
    body: Mapped[dict[str, Any]]


class RawArtifactRow(Base):
    __tablename__ = "raw_artifacts"
    uri: Mapped[str] = mapped_column(String(512), primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str] = mapped_column(String(64))
    run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    classification: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class EvidenceRow(Base):
    __tablename__ = "evidence"
    evidence_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    evidence_type: Mapped[str] = mapped_column(String(48), index=True)
    market: Mapped[str] = mapped_column(String(8))
    need_id: Mapped[str | None] = mapped_column(String(128), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    record_hash: Mapped[str] = mapped_column(String(64))
    body: Mapped[dict[str, Any]]


class MentionRow(Base):
    __tablename__ = "entity_mentions"
    mention_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    need_id: Mapped[str] = mapped_column(String(128), index=True)
    source: Mapped[str] = mapped_column(String(16))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    resolution: Mapped[str] = mapped_column(String(16))
    label: Mapped[str | None] = mapped_column(String(32))
    body: Mapped[dict[str, Any]]


class MetricRow(Base):
    __tablename__ = "metrics"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    market: Mapped[str] = mapped_column(String(8))
    scope: Mapped[str] = mapped_column(String(32))
    scope_id: Mapped[str] = mapped_column(String(256))
    body: Mapped[dict[str, Any]]


class CandidateRow(Base):
    __tablename__ = "gap_candidates"
    candidate_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    market: Mapped[str] = mapped_column(String(8))
    need_id: Mapped[str] = mapped_column(String(128))
    rule_id: Mapped[str] = mapped_column(String(128))
    admission: Mapped[str] = mapped_column(String(32), index=True)
    body: Mapped[dict[str, Any]]


class CardRow(Base):
    __tablename__ = "opportunity_cards"
    card_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    candidate_id: Mapped[str] = mapped_column(String(64))
    market: Mapped[str] = mapped_column(String(8), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    priority: Mapped[str] = mapped_column(String(16))
    score: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)
    body: Mapped[dict[str, Any]]


class ReviewRow(Base):
    __tablename__ = "review_decisions"
    decision_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    resource_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    body: Mapped[dict[str, Any]]


class AuditRow(Base):
    __tablename__ = "audit_events"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True)
    action: Mapped[str] = mapped_column(String(128), index=True)
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str] = mapped_column(String(128), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(32), index=True)
    event_hash: Mapped[str] = mapped_column(String(64))
    body: Mapped[dict[str, Any]]


class AgentRunRow(Base):
    __tablename__ = "agent_runs"
    agent_run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    capability_id: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32))
    body: Mapped[dict[str, Any]]


class PolicyDecisionRow(Base):
    __tablename__ = "policy_decisions"
    decision_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    allowed: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    body: Mapped[dict[str, Any]]


class SpanRow(Base):
    __tablename__ = "spans"
    span_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(32), index=True)
    parent_span_id: Mapped[str | None] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(128))
    start_time: Mapped[datetime]
    end_time: Mapped[datetime]
    duration_ms: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16))
    attributes: Mapped[dict[str, Any]]


class CostRow(Base):
    __tablename__ = "cost_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    category: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(64))
    capability_id: Mapped[str] = mapped_column(String(128))
    units: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(32))
    usd: Mapped[float] = mapped_column(Float)
    simulated: Mapped[int] = mapped_column(Integer)
    trace_id: Mapped[str | None] = mapped_column(String(32))
    span_id: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class EvaluationRunRow(Base):
    __tablename__ = "evaluation_runs"
    evaluation_run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    suite_id: Mapped[str] = mapped_column(String(128), index=True)
    passed: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    body: Mapped[dict[str, Any]]


class SettingRow(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict[str, Any]]
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


APPEND_ONLY = (EvidenceRow, AuditRow, ReviewRow, RawArtifactRow)


def _forbid_mutation(mapper: Any, connection: Any, target: Any) -> None:
    raise ImmutableRecordError(f"{type(target).__name__} is append-only; create a new version instead")


for _cls in APPEND_ONLY:
    event.listen(_cls, "before_update", _forbid_mutation)
    event.listen(_cls, "before_delete", _forbid_mutation)


class Store:
    """Engine + session factory. One per process (per settings)."""

    def __init__(self, url: str) -> None:
        self.url = url
        kwargs: dict[str, Any] = {"future": True}
        if url.startswith("sqlite"):
            path = url.replace("sqlite:///", "", 1)
            if path and path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        self.engine: Engine = create_engine(url, **kwargs)
        if url.startswith("sqlite"):
            event.listen(self.engine, "connect", _sqlite_pragmas)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    def init(self) -> None:
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._sessions()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()
