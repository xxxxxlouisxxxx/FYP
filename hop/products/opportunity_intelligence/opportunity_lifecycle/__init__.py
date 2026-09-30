"""Opportunity Card lifecycle: Draft -> In Review -> Approved / Watchlist / Rejected (spec 7, 11).

Every transition is RBAC-checked, recorded as an immutable ReviewDecision and a hash-chained audit
event, and traced as a "Human review event" span. High-priority approvals require a named reviewer
holding ``review:approve_high_priority`` (the review board). Nothing is auto-approved.
"""

from __future__ import annotations

from dataclasses import dataclass

from hop.platform.common_contracts import ActorType, ReviewAction, ReviewDecision
from hop.platform.observability import current_trace_id
from hop.platform.policy_engine import PolicyViolation
from hop.platform.services import PlatformServices
from hop.products.opportunity_intelligence.contracts import OpportunityCard, OpportunityStatus
from hop.products.opportunity_intelligence.repository import OpportunityRepository

S = OpportunityStatus
TRANSITIONS: dict[OpportunityStatus, dict[ReviewAction, OpportunityStatus]] = {
    S.DRAFT: {ReviewAction.SUBMIT_FOR_REVIEW: S.IN_REVIEW},
    S.IN_REVIEW: {
        ReviewAction.APPROVE: S.APPROVED,
        ReviewAction.WATCHLIST: S.WATCHLIST,
        ReviewAction.REJECT: S.REJECTED,
    },
    S.APPROVED: {ReviewAction.REOPEN: S.IN_REVIEW},
    S.WATCHLIST: {ReviewAction.REOPEN: S.IN_REVIEW, ReviewAction.APPROVE: S.APPROVED, ReviewAction.REJECT: S.REJECTED},
    S.REJECTED: {ReviewAction.REOPEN: S.IN_REVIEW},
}
ANONYMOUS = {"", "anonymous", "system", "unknown", "cli", "api"}


class LifecycleError(ValueError):
    pass


@dataclass
class ReviewOutcome:
    card: OpportunityCard
    decisions: list[ReviewDecision]


class OpportunityLifecycle:
    def __init__(self, platform: PlatformServices, repo: OpportunityRepository) -> None:
        self.platform = platform
        self.repo = repo

    def allowed_actions(self, card: OpportunityCard) -> list[ReviewAction]:
        return list(TRANSITIONS.get(card.status, {}))

    def review(
        self,
        card_id: str,
        action: ReviewAction | str,
        *,
        reviewer: str,
        role: str,
        rationale: str | None = None,
        owner: str | None = None,
        proposed_action: str | None = None,
        auto_submit: bool = True,
    ) -> ReviewOutcome:
        action = ReviewAction(action)
        card = self.repo.card(card_id)
        if card is None:
            raise LifecycleError(f"opportunity card {card_id} not found")
        if reviewer.strip().lower() in ANONYMOUS or len(reviewer.strip()) < 2:
            raise LifecycleError("a named human reviewer is required")
        decisions: list[ReviewDecision] = []
        with self.platform.telemetry.span(
            "Human review event",
            {"card.id": card_id, "review.action": action.value, "reviewer.role": role, "card.priority": card.priority},
        ):
            # Validate the requested decision first so a denied approval leaves the card untouched.
            self._validate(card, action, reviewer, role, rationale, owner)
            if action != ReviewAction.SUBMIT_FOR_REVIEW and card.status == S.DRAFT and auto_submit:
                card, d = self._transition(card, ReviewAction.SUBMIT_FOR_REVIEW, reviewer, role, None, None, None)
                decisions.append(d)
            card, d = self._transition(card, action, reviewer, role, rationale, owner, proposed_action)
            decisions.append(d)
        return ReviewOutcome(card, decisions)

    def _validate(
        self,
        card: OpportunityCard,
        action: ReviewAction,
        reviewer: str,
        role: str,
        rationale: str | None,
        owner: str | None,
    ) -> None:
        permission = "review:submit" if action == ReviewAction.SUBMIT_FOR_REVIEW else "review:decide"
        policy = self.platform.policy
        try:
            policy.enforce_permission(reviewer, role, permission, card.card_id)
            if action == ReviewAction.APPROVE and card.priority == "HIGH":
                policy.enforce_permission(reviewer, role, "review:approve_high_priority", card.card_id)
        except PolicyViolation:
            self.platform.audit.record(
                actor=reviewer,
                actor_type=ActorType.HUMAN,
                action=f"opportunity.{action.value.lower()}",
                resource_type="opportunity_card",
                resource_id=card.card_id,
                outcome="DENIED",
                details={"role": role, "priority": card.priority},
                trace_id=current_trace_id(),
            )
            raise
        needs_rationale = (ReviewAction.REJECT, ReviewAction.WATCHLIST, ReviewAction.REOPEN)
        if action in needs_rationale and not (rationale or "").strip():
            raise LifecycleError(f"{action.value} requires a rationale")
        if action == ReviewAction.APPROVE and not (owner or card.owner):
            raise LifecycleError("approval requires an accountable owner")

    def _transition(
        self,
        card: OpportunityCard,
        action: ReviewAction,
        reviewer: str,
        role: str,
        rationale: str | None,
        owner: str | None,
        proposed_action: str | None,
    ) -> tuple[OpportunityCard, ReviewDecision]:
        target = TRANSITIONS.get(card.status, {}).get(action)
        if target is None:
            raise LifecycleError(
                f"cannot {action.value} a card in status {card.status.value}; "
                f"allowed: {[a.value for a in self.allowed_actions(card)]}"
            )
        self._validate(card, action, reviewer, role, rationale, owner)
        decision = ReviewDecision(
            resource_id=card.card_id,
            action=action,
            from_status=card.status.value,
            to_status=target.value,
            reviewer=reviewer,
            reviewer_role=role,
            rationale=rationale,
            owner_assigned=owner,
            proposed_action=proposed_action,
            trace_id=current_trace_id(),
        )
        card = card.model_copy(deep=True)
        card.status = target
        if owner:
            card.owner = owner
        if proposed_action:
            card.proposed_action = proposed_action
        if action == ReviewAction.APPROVE:
            card.approver = reviewer
        self.repo.add_review(decision)
        self.repo.save_card(card)
        self.platform.audit.record(
            actor=reviewer,
            actor_type=ActorType.HUMAN,
            action=f"opportunity.{action.value.lower()}",
            resource_type="opportunity_card",
            resource_id=card.card_id,
            details={
                "from": decision.from_status,
                "to": decision.to_status,
                "role": role,
                "priority": card.priority,
                "decision_id": decision.decision_id,
                "rationale": (rationale or "")[:300],
            },
            trace_id=current_trace_id(),
        )
        return card, decision
