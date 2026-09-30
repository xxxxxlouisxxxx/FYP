"""Platform HTTP API: runs, traces, evidence, audit, capabilities, policy and cost endpoints.

Products mount their own routers on the app returned by ``create_platform_app``. Identity comes from
``X-HOP-User`` / ``X-HOP-Role`` headers - a placeholder for Microsoft Entra ID tokens mapped to roles.
Incoming W3C ``traceparent`` headers are continued so client, API and workflow spans share one trace.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from hop.platform.observability import outbound_trace_headers, span_tree
from hop.platform.policy_engine import KillSwitchEngaged, PolicyViolation
from hop.platform.services import PlatformServices


@dataclass(frozen=True)
class Principal:
    user: str
    role: str


def principal(
    x_hop_user: str = Header("anonymous", description="Caller identity (Entra ID placeholder)"),
    x_hop_role: str = Header("viewer", description="Caller role: viewer, analyst, domain_reviewer, review_board, ..."),
) -> Principal:
    return Principal(user=x_hop_user, role=x_hop_role)


def services(request: Request) -> PlatformServices:
    return request.app.state.platform


def require(permission: str) -> Callable[..., Principal]:
    def dep(p: Principal = Depends(principal), svc: PlatformServices = Depends(services)) -> Principal:
        decision = svc.policy.check_permission(p.user, p.role, permission)
        if not decision.allowed:
            raise HTTPException(status_code=403, detail=decision.reason)
        return p

    return dep


def create_platform_app(
    platform: PlatformServices, *, title: str = "HOP Platform API", version: str = "0.1.0"
) -> FastAPI:
    app = FastAPI(title=title, version=version)
    app.state.platform = platform

    @app.middleware("http")
    async def trace_requests(request: Request, call_next: Any) -> Any:
        with (
            platform.telemetry.continue_trace(request.headers.get("traceparent")),
            platform.telemetry.span(
                f"API {request.method} {request.url.path}",
                {"http.method": request.method, "http.route": request.url.path},
            ) as span,
        ):
            response = await call_next(request)
            span.set_attribute("http.status_code", response.status_code)
            for k, v in outbound_trace_headers().items():
                response.headers[k] = v
            return response

    @app.exception_handler(PolicyViolation)
    async def _policy(_: Request, exc: PolicyViolation) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": exc.decision.reason, "action": exc.decision.action})

    @app.exception_handler(KillSwitchEngaged)
    async def _killed(_: Request, exc: KillSwitchEngaged) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.get("/health", tags=["platform"])
    def health() -> dict[str, Any]:
        ok, events = platform.audit.verify_chain()
        return {
            "status": "ok",
            "env": platform.settings.env,
            "database": platform.store.url.split("://", 1)[0],
            "kill_switch": platform.kill_switch.engaged(),
            "audit_chain_valid": ok,
            "audit_events": events,
            "default_model": platform.gateway.default_model,
        }

    @app.get("/runs", tags=["runs"])
    def list_runs(limit: int = 50, _: Principal = Depends(require("run:read"))) -> list[dict[str, Any]]:
        return [r.model_dump(mode="json") for r in platform.runtime.list_runs(limit)]

    @app.get("/runs/{run_id}", tags=["runs"])
    def get_run(run_id: str, _: Principal = Depends(require("run:read"))) -> dict[str, Any]:
        run = platform.runtime.get(run_id)
        if run is None:
            raise HTTPException(404, f"run {run_id} not found")
        return {**run.model_dump(mode="json"), "costs": platform.costs.breakdown(run_id)}

    @app.post("/runs/{run_id}/cancel", tags=["runs"])
    def cancel_run(run_id: str, p: Principal = Depends(require("run:create"))) -> dict[str, str]:
        try:
            platform.runtime.cancel(run_id, p.user)
        except KeyError as exc:
            raise HTTPException(404, f"run {run_id} not found") from exc
        return {"run_id": run_id, "status": "CANCELLED"}

    @app.get("/traces/{trace_id}", tags=["observability"])
    def get_trace(trace_id: str, _: Principal = Depends(require("trace:read"))) -> dict[str, Any]:
        spans = platform.telemetry.spans_for_trace(trace_id)
        if not spans:
            raise HTTPException(404, f"trace {trace_id} not found")
        return {
            "trace_id": trace_id,
            "span_count": len(spans),
            "tree": [{"depth": d, "name": s["name"], "duration_ms": s["duration_ms"], "status": s["status"]}
                     for d, s in span_tree(spans)],
            "spans": spans,
        }  # fmt: skip

    @app.get("/evidence/{evidence_id}", tags=["evidence"])
    def get_evidence(evidence_id: str, _: Principal = Depends(require("evidence:read"))) -> dict[str, Any]:
        item = platform.evidence.get(evidence_id)
        if item is None:
            raise HTTPException(404, f"evidence {evidence_id} not found")
        lineage = platform.evidence.verify_lineage(evidence_id)
        return {
            "evidence": item.model_dump(mode="json"),
            "versions": len(platform.evidence.history(evidence_id)),
            "lineage": {"valid": lineage.valid, "reason": lineage.reason},
        }

    @app.get("/evidence/{evidence_id}/raw", tags=["evidence"])
    def get_evidence_raw(evidence_id: str, _: Principal = Depends(require("evidence:raw_read"))) -> dict[str, Any]:
        item = platform.evidence.get(evidence_id)
        if item is None:
            raise HTTPException(404, f"evidence {evidence_id} not found")
        raw = platform.evidence.read_raw(item.raw_payload_uri)
        return {"uri": item.raw_payload_uri, "sha256": item.content_hash, "untrusted_content": True,
                "payload": raw.decode("utf-8", errors="replace")}  # fmt: skip

    @app.get("/audit", tags=["governance"])
    def audit(
        resource_id: str | None = None, limit: int = 100, _: Principal = Depends(require("run:read"))
    ) -> dict[str, Any]:
        ok, n = platform.audit.verify_chain()
        events = platform.audit.list(resource_id=resource_id, limit=limit)
        return {"chain_valid": ok, "total_events": n, "events": [e.model_dump(mode="json") for e in events]}

    @app.get("/capabilities", tags=["governance"])
    def capabilities(_: Principal = Depends(require("run:read"))) -> list[dict[str, Any]]:
        out = []
        for m in platform.registry.all():
            ok, reason = platform.registry.executable_status(m.capability_id, platform.settings.env)
            out.append({**m.model_dump(mode="json"), "executable": ok, "executable_reason": reason})
        return out

    @app.get("/policy/decisions", tags=["governance"])
    def policy_decisions(
        allowed: bool | None = None, limit: int = 100, _: Principal = Depends(require("run:read"))
    ) -> list[dict[str, Any]]:
        return [d.model_dump(mode="json") for d in platform.policy.decisions(allowed=allowed, limit=limit)]

    @app.get("/costs", tags=["observability"])
    def costs(run_id: str | None = None, _: Principal = Depends(require("run:read"))) -> list[dict[str, Any]]:
        return platform.costs.breakdown(run_id)

    return app
