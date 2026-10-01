"""Persistence for the Opportunity Intelligence product on the platform's relational store."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select

from hop.platform.common_contracts import Observation, ReviewDecision, utcnow
from hop.platform.storage.db import (
    CandidateRow,
    CardRow,
    MentionRow,
    MetricRow,
    ObservationRow,
    ReviewRow,
    RunRow,
    Store,
)
from hop.products.opportunity_intelligence.contracts import GapCandidate, OpportunityCard


class OpportunityRepository:
    def __init__(self, store: Store) -> None:
        self.store = store

    # observations -------------------------------------------------------------------------
    def upsert_observation(self, obs: Observation) -> None:
        with self.store.session() as s:
            s.merge(
                ObservationRow(
                    observation_id=obs.observation_id,
                    run_id=obs.run_id,
                    signal_family=obs.signal_family.value,
                    market=obs.market,
                    query_id=obs.query_id,
                    need_id=obs.need_id,
                    status=obs.status.value,
                    body=obs.model_dump(mode="json"),
                )
            )

    def observations(self, run_id: str, family: str | None = None) -> list[Observation]:
        with self.store.session() as s:
            q = select(ObservationRow).where(ObservationRow.run_id == run_id)
            if family:
                q = q.where(ObservationRow.signal_family == family)
            rows = s.execute(q.order_by(ObservationRow.observation_id)).scalars()
            return [Observation.model_validate(r.body) for r in rows]

    # mentions -----------------------------------------------------------------------------
    def replace_mentions(self, run_id: str, mentions: list[dict[str, Any]]) -> None:
        with self.store.session() as s:
            s.execute(delete(MentionRow).where(MentionRow.run_id == run_id))
            for m in mentions:
                s.add(
                    MentionRow(
                        mention_id=m["mention_id"],
                        run_id=run_id,
                        need_id=m["need_id"],
                        source=m["source"],
                        entity_id=m.get("entity_id"),
                        resolution=m["resolution"],
                        label=m.get("label"),
                        body=m,
                    )
                )

    def mentions(self, run_id: str, source: str | None = None) -> list[dict[str, Any]]:
        with self.store.session() as s:
            q = select(MentionRow).where(MentionRow.run_id == run_id)
            if source:
                q = q.where(MentionRow.source == source)
            return [r.body for r in s.execute(q.order_by(MentionRow.mention_id)).scalars()]

    # metrics ------------------------------------------------------------------------------
    def replace_metrics(self, run_id: str, market: str, records: list[dict[str, Any]]) -> None:
        with self.store.session() as s:
            s.execute(delete(MetricRow).where(MetricRow.run_id == run_id))
            for r in records:
                s.add(MetricRow(run_id=run_id, market=market, scope=r["scope"], scope_id=r["scope_id"], body=r))

    def metrics(self, run_id: str, scope: str | None = None) -> list[dict[str, Any]]:
        with self.store.session() as s:
            q = select(MetricRow).where(MetricRow.run_id == run_id)
            if scope:
                q = q.where(MetricRow.scope == scope)
            return [r.body for r in s.execute(q.order_by(MetricRow.id)).scalars()]

    # candidates ---------------------------------------------------------------------------
    def upsert_candidate(self, c: GapCandidate) -> None:
        with self.store.session() as s:
            s.merge(
                CandidateRow(
                    candidate_id=c.candidate_id,
                    run_id=c.run_id,
                    market=c.market,
                    need_id=c.need_id,
                    rule_id=c.rule_id,
                    admission=c.admission.value,
                    body=c.model_dump(mode="json"),
                )
            )

    def candidates(self, run_id: str | None = None, admission: str | None = None) -> list[GapCandidate]:
        with self.store.session() as s:
            q = select(CandidateRow)
            if run_id:
                q = q.where(CandidateRow.run_id == run_id)
            if admission:
                q = q.where(CandidateRow.admission == admission)
            return [
                GapCandidate.model_validate(r.body) for r in s.execute(q.order_by(CandidateRow.candidate_id)).scalars()
            ]

    def delete_candidates(self, run_id: str) -> None:
        with self.store.session() as s:
            s.execute(delete(CandidateRow).where(CandidateRow.run_id == run_id))

    # cards --------------------------------------------------------------------------------
    def save_card(self, card: OpportunityCard) -> None:
        card.updated_at = utcnow()
        with self.store.session() as s:
            s.merge(
                CardRow(
                    card_id=card.card_id,
                    run_id=card.run_id,
                    candidate_id=card.candidate_id,
                    market=card.market,
                    status=card.status.value,
                    priority=card.priority,
                    score=card.score.total,
                    updated_at=card.updated_at,
                    body=card.model_dump(mode="json"),
                )
            )

    def card(self, card_id: str) -> OpportunityCard | None:
        with self.store.session() as s:
            row = s.get(CardRow, card_id)
            return OpportunityCard.model_validate(row.body) if row else None

    def cards(
        self, *, status: str | None = None, market: str | None = None, run_id: str | None = None, limit: int = 500
    ) -> list[OpportunityCard]:
        with self.store.session() as s:
            q = select(CardRow).order_by(CardRow.score.desc()).limit(limit)
            if status:
                q = q.where(CardRow.status == status.upper())
            if market:
                q = q.where(CardRow.market == market)
            if run_id:
                q = q.where(CardRow.run_id == run_id)
            return [OpportunityCard.model_validate(r.body) for r in s.execute(q).scalars()]

    # reviews ------------------------------------------------------------------------------
    def add_review(self, decision: ReviewDecision) -> None:
        with self.store.session() as s:
            s.add(
                ReviewRow(
                    decision_id=decision.decision_id,
                    resource_id=decision.resource_id,
                    body=decision.model_dump(mode="json"),
                )
            )

    def reviews(self, card_id: str | None = None) -> list[ReviewDecision]:
        with self.store.session() as s:
            q = select(ReviewRow).order_by(ReviewRow.created_at)
            if card_id:
                q = q.where(ReviewRow.resource_id == card_id)
            return [ReviewDecision.model_validate(r.body) for r in s.execute(q).scalars()]

    # runs ---------------------------------------------------------------------------------
    def latest_successful_run(self, market: str | None = None) -> str | None:
        with self.store.session() as s:
            q = select(RunRow.run_id).where(RunRow.status == "SUCCEEDED").order_by(RunRow.created_at.desc())
            if market:
                q = q.where(RunRow.market == market)
            return s.execute(q.limit(1)).scalar()
