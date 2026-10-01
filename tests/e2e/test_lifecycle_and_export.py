from __future__ import annotations

import csv
import io
import json

import pytest

from hop.platform.common_contracts import ReviewAction
from hop.platform.policy_engine import PolicyViolation
from hop.products.opportunity_intelligence.contracts import OpportunityCard, OpportunityStatus
from hop.products.opportunity_intelligence.opportunity_lifecycle import LifecycleError
from hop.products.opportunity_intelligence.opportunity_lifecycle.export import export_cards
from tests.conftest import Discovery


def _card(d: Discovery, priority: str) -> OpportunityCard:
    return next(c for c in d.app.repo.cards(run_id=d.run.run_id) if c.priority == priority)


def test_high_priority_needs_review_board_and_denial_leaves_card_untouched(fresh_discovery: Discovery) -> None:
    app = fresh_discovery.app
    card = _card(fresh_discovery, "HIGH")
    assert card.required_approver_role == "review_board"
    with pytest.raises(PolicyViolation):
        app.lifecycle.review(card.card_id, ReviewAction.APPROVE, reviewer="Sam Analyst", role="analyst", owner="Desk")
    assert app.repo.card(card.card_id).status == OpportunityStatus.DRAFT
    assert app.repo.reviews(card.card_id) == []
    denied = [e for e in app.platform.audit.list(resource_id=card.card_id) if e.outcome == "DENIED"]
    assert denied and denied[0].actor == "Sam Analyst"

    outcome = app.lifecycle.review(
        card.card_id, ReviewAction.APPROVE, reviewer="Ada Chan", role="review_board", owner="Sourcing Desk HK"
    )
    assert outcome.card.status == OpportunityStatus.APPROVED
    assert outcome.card.approver == "Ada Chan" and outcome.card.owner == "Sourcing Desk HK"
    assert [d.action for d in outcome.decisions] == [ReviewAction.SUBMIT_FOR_REVIEW, ReviewAction.APPROVE]
    assert [d.to_status for d in app.repo.reviews(card.card_id)] == ["IN_REVIEW", "APPROVED"]
    assert app.platform.audit.verify_chain()[0]


def test_review_rules(fresh_discovery: Discovery) -> None:
    app = fresh_discovery.app
    card = _card(fresh_discovery, "MEDIUM")
    with pytest.raises(LifecycleError, match="named human reviewer"):
        app.lifecycle.review(card.card_id, ReviewAction.REJECT, reviewer="anonymous", role="analyst", rationale="x")
    with pytest.raises(LifecycleError, match="rationale"):
        app.lifecycle.review(card.card_id, ReviewAction.REJECT, reviewer="Sam Analyst", role="analyst")
    with pytest.raises(LifecycleError, match="owner"):
        app.lifecycle.review(card.card_id, ReviewAction.APPROVE, reviewer="Sam Analyst", role="analyst")
    with pytest.raises(PolicyViolation):
        app.lifecycle.review(card.card_id, ReviewAction.WATCHLIST, reviewer="Vic Viewer", role="viewer", rationale="x")
    assert app.repo.card(card.card_id).status == OpportunityStatus.DRAFT

    out = app.lifecycle.review(
        card.card_id, ReviewAction.WATCHLIST, reviewer="Sam Analyst", role="analyst", rationale="needs Q4 data"
    )
    assert out.card.status == OpportunityStatus.WATCHLIST
    out = app.lifecycle.review(card.card_id, ReviewAction.APPROVE, reviewer="Sam Analyst", role="analyst", owner="Desk")
    assert out.card.status == OpportunityStatus.APPROVED
    with pytest.raises(LifecycleError, match="cannot"):
        app.lifecycle.review(card.card_id, ReviewAction.REJECT, reviewer="Sam Analyst", role="analyst", rationale="x")
    out = app.lifecycle.review(
        card.card_id, ReviewAction.REOPEN, reviewer="Sam Analyst", role="analyst", rationale="new evidence"
    )
    assert out.card.status == OpportunityStatus.IN_REVIEW


@pytest.mark.parametrize("fmt", ["json", "csv"])
def test_governed_export_is_stored_and_audited(fresh_discovery: Discovery, fmt: str) -> None:
    app = fresh_discovery.app
    cards = app.repo.cards(run_id=fresh_discovery.run.run_id)
    uri, data = export_cards(app.platform, cards, fmt=fmt, actor="Sam Analyst")
    assert app.platform.evidence.read_raw(uri) == data
    if fmt == "json":
        assert {c["card_id"] for c in json.loads(data)} == {c.card_id for c in cards}
    else:
        rows = list(csv.DictReader(io.StringIO(data.decode())))
        assert len(rows) == len(cards) and all(r["rule_version"] and r["score_version"] for r in rows)
    assert any(e.action == "opportunity.export" and e.actor == "Sam Analyst" for e in app.platform.audit.list())


def test_export_denied_when_capability_revoked(fresh_discovery: Discovery) -> None:
    app = fresh_discovery.app
    app.platform.registry.revoke("opportunity.exporter", "data-sharing review")
    with pytest.raises(PolicyViolation):
        export_cards(app.platform, [], fmt="csv", actor="Sam Analyst")
