"""Opportunity Intelligence HTTP routes: discovery runs, cost estimates, cards, reviews and gap candidates."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from hop.platform.api import Principal, require
from hop.platform.common_contracts import CollectionRequest, ReviewAction
from hop.products.opportunity_intelligence.opportunity_lifecycle import LifecycleError


class RunCreate(BaseModel):
    market: str = Field(pattern=r"^[A-Z]{2}$", examples=["HK"])
    tier: str = Field(default="A", pattern=r"^[A-Z]$")
    language: str | None = None
    gerp_repeats: int | None = Field(default=None, ge=1, le=10)
    budget_usd: float | None = Field(default=None, gt=0)
    budget_approved_by: str | None = None
    provider: Literal["auto", "sandbox", "dataforseo"] = "auto"
    decision_question: str | None = None
    force_new: bool = False


class ReviewRequest(BaseModel):
    action: ReviewAction
    rationale: str | None = None
    owner: str | None = None
    proposed_action: str | None = None


def build_router(app_ctx: Any) -> APIRouter:
    """``app_ctx`` is the composed ``hop.bootstrap.App`` (passed in to keep this module import-light)."""
    from hop.products.opportunity_intelligence.opportunity_lifecycle.export import export_cards
    from hop.products.opportunity_intelligence.pipeline import _estimate, start_discovery

    router = APIRouter(tags=["opportunity-intelligence"])

    def to_request(body: RunCreate, user: str) -> CollectionRequest:
        return CollectionRequest(
            domain_pack=app_ctx.pack.pack_id, market=body.market, tier=body.tier, language=body.language,
            gerp_repeats=body.gerp_repeats, budget_usd=body.budget_usd, budget_approved_by=body.budget_approved_by,
            serp_provider=body.provider, decision_question=body.decision_question, requested_by=user,
        )  # fmt: skip

    @router.post("/runs", status_code=201)
    def create_run(body: RunCreate, p: Principal = Depends(require("run:create"))) -> dict[str, Any]:
        try:
            deps = app_ctx.discovery_deps(body.provider)
            run = start_discovery(deps, to_request(body, p.user), force_new=body.force_new)
        except (KeyError, ValueError, RuntimeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        cards = app_ctx.repo.cards(run_id=run.run_id)
        return {**run.model_dump(mode="json"), "cards": [c.card_id for c in cards]}

    @router.post("/runs/estimate")
    def estimate(body: RunCreate, p: Principal = Depends(require("run:read"))) -> dict[str, Any]:
        try:
            deps = app_ctx.discovery_deps(body.provider)
            return _estimate(deps, to_request(body, p.user)).model_dump(mode="json")
        except (KeyError, ValueError, RuntimeError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/opportunities")
    def list_opportunities(
        status: str | None = None,
        market: str | None = None,
        run_id: str | None = None,
        _: Principal = Depends(require("opportunity:read")),
    ) -> list[dict[str, Any]]:
        return [
            {"card_id": c.card_id, "title": c.title, "status": c.status.value, "priority": c.priority,
             "score": c.score.total, "confidence_label": c.confidence_label, "market": c.market, "need_id": c.need_id,
             "brand_id": c.brand_id, "gap_family": c.gap_family, "run_id": c.run_id,
             "supporting_evidence": len(c.supporting_evidence_ids), "counter_evidence": len(c.counter_evidence_ids)}
            for c in app_ctx.repo.cards(status=status, market=market, run_id=run_id)
        ]  # fmt: skip

    @router.get("/opportunities/export")
    def export(
        fmt: Literal["json", "csv"] = "json",
        status: str | None = None,
        p: Principal = Depends(require("opportunity:read")),
    ) -> Response:
        uri, data = export_cards(app_ctx.platform, app_ctx.repo.cards(status=status), fmt=fmt, actor=p.user)
        return Response(
            content=data,
            media_type="text/csv" if fmt == "csv" else "application/json",
            headers={"X-HOP-Export-URI": uri},
        )

    @router.get("/opportunities/{card_id}")
    def get_opportunity(card_id: str, _: Principal = Depends(require("opportunity:read"))) -> dict[str, Any]:
        card = app_ctx.repo.card(card_id)
        if card is None:
            raise HTTPException(404, f"card {card_id} not found")
        return {
            "card": card.model_dump(mode="json"),
            "allowed_actions": [a.value for a in app_ctx.lifecycle.allowed_actions(card)],
            "reviews": [d.model_dump(mode="json") for d in app_ctx.repo.reviews(card_id)],
        }

    @router.get("/opportunities/{card_id}/evidence")
    def card_evidence(card_id: str, _: Principal = Depends(require("evidence:read"))) -> dict[str, Any]:
        card = app_ctx.repo.card(card_id)
        if card is None:
            raise HTTPException(404, f"card {card_id} not found")
        ev = app_ctx.platform.evidence

        def items(ids: list[str]) -> list[dict[str, Any]]:
            return [e.model_dump(mode="json") for e in (ev.get(i) for i in ids) if e is not None]

        return {"supporting": items(card.supporting_evidence_ids), "counter": items(card.counter_evidence_ids)}

    @router.post("/opportunities/{card_id}/review")
    def review(card_id: str, body: ReviewRequest, p: Principal = Depends(require("review:submit"))) -> dict[str, Any]:
        try:
            outcome = app_ctx.lifecycle.review(
                card_id,
                body.action,
                reviewer=p.user,
                role=p.role,
                rationale=body.rationale,
                owner=body.owner,
                proposed_action=body.proposed_action,
            )
        except LifecycleError as exc:
            raise HTTPException(409 if "cannot" in str(exc) else 422, str(exc)) from exc
        return {"card_id": card_id, "status": outcome.card.status.value,
                "decisions": [d.model_dump(mode="json") for d in outcome.decisions]}  # fmt: skip

    @router.get("/candidates")
    def candidates(run_id: str, _: Principal = Depends(require("opportunity:read"))) -> list[dict[str, Any]]:
        return [c.model_dump(mode="json") for c in app_ctx.repo.candidates(run_id)]

    return router
