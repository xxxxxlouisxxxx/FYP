"""Collection activities: cost estimate, consumer-demand, SERP and governed GERP observation."""

from __future__ import annotations

from typing import Any

from hop.platform.common_contracts import (
    CollectionRequest,
    CostEstimate,
    CostLine,
    Device,
    Observation,
    SignalFamily,
    ValueState,
    stable_id,
    utcnow,
)
from hop.platform.domain_registry import DomainPack, QuerySpec
from hop.platform.integrations import ProviderResponse
from hop.platform.integrations.dataforseo import SERP_PARSER_VERSION, VOLUME_PARSER_VERSION
from hop.platform.model_gateway import AbstentionReason
from hop.platform.observability import current_trace_id
from hop.platform.workflow_runtime import BudgetExceeded, RetryOutcome, RetryPolicy, RunContext, retry_call
from hop.products.opportunity_intelligence.deps import DiscoveryDeps
from hop.products.opportunity_intelligence.schemas import GerpAnswerOutput, GerpExtractionOutput

PROVIDER_RETRY = RetryPolicy(max_attempts=3, base_delay_s=0.05, max_delay_s=0.4)

ANSWER_TOKENS = (220, 380)
EXTRACTION_TOKENS = (1100, 350)
EXPLANATION_TOKENS = (700, 220)


def _request(ctx: RunContext) -> CollectionRequest:
    return CollectionRequest.model_validate(ctx.request)


def repeats_for(pack: DomainPack, req: CollectionRequest) -> int:
    return req.gerp_repeats or pack.market(req.market).tiers[req.tier].gerp_repeats


def budget_for(pack: DomainPack, req: CollectionRequest) -> float:
    tier_budget = pack.market(req.market).tiers[req.tier].max_budget_usd
    if req.budget_usd is None:
        return tier_budget
    if req.budget_usd > tier_budget and not req.budget_approved_by:
        raise BudgetExceeded(
            f"requested budget ${req.budget_usd:.2f} exceeds tier limit ${tier_budget:.2f}; a named approver is required"
        )
    return req.budget_usd


def estimate_cost(
    pack: DomainPack,
    req: CollectionRequest,
    *,
    serp_unit: float,
    demand_unit: float,
    model_pricing: tuple[float, float],
    simulated: bool,
) -> CostEstimate:
    queries = pack.queries_for(req.market, req.tier, req.language)
    languages = sorted({q.language for q in queries})
    repeats = repeats_for(pack, req)
    pin, pout = model_pricing

    def tokens(n: int, t: tuple[int, int]) -> float:
        return n * (t[0] / 1000 * pin + t[1] / 1000 * pout)

    lines: list[CostLine] = []
    fams = set(req.signal_families)
    if SignalFamily.DEMAND in fams:
        lines.append(
            CostLine(
                item="demand.search_volume",
                provider="dataforseo-compatible",
                units=len(languages),
                unit="provider_task",
                unit_cost_usd=demand_unit,
                total_usd=round(len(languages) * demand_unit, 6),
                simulated=simulated,
            )
        )
    if SignalFamily.SERP in fams:
        lines.append(
            CostLine(
                item="serp.organic_live",
                provider="dataforseo-compatible",
                units=len(queries),
                unit="provider_task",
                unit_cost_usd=serp_unit,
                total_usd=round(len(queries) * serp_unit, 6),
                simulated=simulated,
            )
        )
    if SignalFamily.GERP in fams:
        n = len(queries) * repeats
        lines.append(
            CostLine(
                item="gerp.answer",
                provider="model_gateway",
                units=n,
                unit="model_call",
                unit_cost_usd=round(tokens(1, ANSWER_TOKENS), 8),
                total_usd=round(tokens(n, ANSWER_TOKENS), 6),
                simulated=simulated,
            )
        )
        lines.append(
            CostLine(
                item="gerp.extraction",
                provider="model_gateway",
                units=n,
                unit="model_call",
                unit_cost_usd=round(tokens(1, EXTRACTION_TOKENS), 8),
                total_usd=round(tokens(n, EXTRACTION_TOKENS), 6),
                simulated=simulated,
            )
        )
    n_expl = max(1, len(queries))
    lines.append(
        CostLine(
            item="opportunity.explanation (upper bound)",
            provider="model_gateway",
            units=n_expl,
            unit="model_call",
            unit_cost_usd=round(tokens(1, EXPLANATION_TOKENS), 8),
            total_usd=round(tokens(n_expl, EXPLANATION_TOKENS), 6),
            simulated=simulated,
        )
    )
    total = round(sum(line.total_usd for line in lines), 6)
    budget = budget_for(pack, req)
    return CostEstimate(lines=lines, total_usd=total, budget_usd=budget, within_budget=total <= budget)


def _base_obs(
    ctx: RunContext, pack: DomainPack, req: CollectionRequest, q: QuerySpec, family: SignalFamily, repeat: int = 0
) -> dict[str, Any]:
    market = pack.market(req.market)
    loc = market.locale_for(q.language)
    return {
        "observation_id": stable_id("obs", ctx.run_id, family.value, q.query_id, repeat),
        "run_id": ctx.run_id,
        "signal_family": family,
        "market": req.market,
        "locale": loc.locale,
        "language": q.language,
        "device": req.device or market.default_device,
        "query_id": q.query_id,
        "query_text": q.text,
        "need_id": q.need_id,
        "repeat_index": repeat,
        "observed_at": utcnow(),
        "trace_id": current_trace_id(),
    }


def _provider_call(
    ctx: RunContext, fn: Any, span_name: str, attrs: dict[str, Any], unit_cost: float, capability_id: str
) -> tuple[ProviderResponse | None, str | None, int]:
    """Call a provider with retries. Transient exhaustion degrades to PROVIDER_ERROR, never to zero."""
    if not ctx.budget.can_spend(unit_cost):
        raise BudgetExceeded(f"insufficient budget for {capability_id}")
    outcome = RetryOutcome()
    with ctx.span(span_name, {**attrs, "capability.id": capability_id}) as span:
        try:
            resp = retry_call(fn, PROVIDER_RETRY, sleep=ctx.runtime.sleep, outcome=outcome)
        except Exception as exc:
            from hop.platform.policy_engine import KillSwitchEngaged, PolicyViolation

            if isinstance(exc, KillSwitchEngaged | PolicyViolation | BudgetExceeded):
                raise
            span.set_attribute("retry.count", outcome.retries)
            span.set_attribute("error.class", type(exc).__name__)
            return None, f"{type(exc).__name__}: {exc}", outcome.retries
        span.set_attribute("retry.count", outcome.retries)
        span.set_attribute("provider.task_id", resp.task_id or "")
        span.set_attribute("provider.status", resp.status)
        span.set_attribute("cost.usd", resp.cost_usd)
        if resp.status == "ok" and resp.cost_usd:
            ctx.spend(
                resp.cost_usd,
                category="provider",
                provider=resp.provider,
                capability_id=capability_id,
                units=1,
                unit="provider_task",
                simulated=resp.simulated,
            )
        return resp, None, outcome.retries


def collect_demand(ctx: RunContext) -> dict[str, Any]:
    deps: DiscoveryDeps = ctx.deps
    req = _request(ctx)
    if SignalFamily.DEMAND not in req.signal_families:
        return {"skipped": "demand not requested"}
    pack = deps.pack
    market = pack.market(req.market)
    provider = deps.demand_provider(ctx.run_id)
    queries = pack.queries_for(req.market, req.tier, req.language)
    by_lang: dict[str, list[QuerySpec]] = {}
    for q in queries:
        by_lang.setdefault(q.language, []).append(q)
    counts: dict[str, int] = {}
    for lang, qs in sorted(by_lang.items()):
        ctx.check_controls()
        loc = market.locale_for(lang)
        resp, error, retries = _provider_call(
            ctx,
            lambda loc=loc, qs=qs: provider.fetch_search_volume(
                market=req.market,
                keywords=[q.text for q in qs],
                location_code=market.provider_location_code,
                language_code=loc.provider_language_code,
            ),
            "Provider submission",
            {"signal.family": "demand", "language": lang, "keywords": len(qs)},
            provider.unit_cost_usd,
            provider.capability_id,
        )
        artifact = None
        if resp is not None and resp.raw is not None:
            artifact = deps.platform.evidence.persist_raw(resp.raw, run_id=ctx.run_id, namespace="raw/demand")
        for q in qs:
            status, err = _status(resp, error)
            obs = Observation(
                **_base_obs(ctx, pack, req, q, SignalFamily.DEMAND),
                provider=resp.provider if resp else provider.name,
                endpoint=resp.endpoint if resp else "search_volume",
                status=status,
                raw_artifact_uri=artifact.uri if artifact else None,
                content_hash=artifact.sha256 if artifact else None,
                parser_version=VOLUME_PARSER_VERSION,
                provider_task_id=resp.task_id if resp else None,
                cost_usd=round((resp.cost_usd if resp and resp.status == "ok" else 0.0) / len(qs), 8),
                simulated=resp.simulated if resp else True,
                retry_count=retries,
                error=err,
            )
            deps.repo.upsert_observation(obs)
            counts[status.value] = counts.get(status.value, 0) + 1
    return {"observations": sum(counts.values()), "by_status": counts, "provider": provider.name}


def _status(resp: ProviderResponse | None, error: str | None) -> tuple[ValueState, str | None]:
    if resp is None:
        return ValueState.PROVIDER_ERROR, error
    if resp.status == "ok":
        return ValueState.OBSERVED_VALUE, None
    if resp.status == "not_collected":
        return ValueState.NOT_COLLECTED, resp.error
    return ValueState.PROVIDER_ERROR, resp.error


def collect_serp(ctx: RunContext) -> dict[str, Any]:
    deps: DiscoveryDeps = ctx.deps
    req = _request(ctx)
    if SignalFamily.SERP not in req.signal_families:
        return {"skipped": "serp not requested"}
    pack = deps.pack
    market = pack.market(req.market)
    provider = deps.serp_provider(ctx.run_id)
    counts: dict[str, int] = {}
    retries_total = 0
    for q in pack.queries_for(req.market, req.tier, req.language):
        ctx.check_controls()
        loc = market.locale_for(q.language)
        device: Device = req.device or market.default_device
        resp, error, retries = _provider_call(
            ctx,
            lambda q=q, loc=loc, device=device: provider.fetch_serp(
                market=req.market,
                query_id=q.query_id,
                keyword=q.text,
                location_code=market.provider_location_code,
                language_code=loc.provider_language_code,
                device=device.value,
                depth=10,
            ),
            "Provider submission",
            {"signal.family": "serp", "query.id": q.query_id},
            provider.unit_cost_usd,
            provider.capability_id,
        )
        retries_total += retries
        with ctx.span("Polling", {"query.id": q.query_id, "polling.mode": "live endpoint (no task polling)"}):
            pass
        artifact = None
        if resp is not None and resp.raw is not None:
            artifact = deps.platform.evidence.persist_raw(resp.raw, run_id=ctx.run_id, namespace="raw/serp")
        status, err = _status(resp, error)
        obs = Observation(
            **_base_obs(ctx, pack, req, q, SignalFamily.SERP),
            provider=resp.provider if resp else provider.name,
            endpoint=resp.endpoint if resp else "serp",
            status=status,
            raw_artifact_uri=artifact.uri if artifact else None,
            content_hash=artifact.sha256 if artifact else None,
            parser_version=SERP_PARSER_VERSION,
            provider_task_id=resp.task_id if resp else None,
            cost_usd=resp.cost_usd if resp and resp.status == "ok" else 0.0,
            simulated=resp.simulated if resp else True,
            retry_count=retries,
            error=err,
        )
        deps.repo.upsert_observation(obs)
        counts[status.value] = counts.get(status.value, 0) + 1
    return {
        "observations": sum(counts.values()),
        "by_status": counts,
        "retries": retries_total,
        "provider": provider.name,
    }


_ABSTAIN_STATE = {
    AbstentionReason.BUDGET_EXCEEDED: ValueState.SUPPRESSED_BY_POLICY,
    AbstentionReason.MODEL_ABSTAINED: ValueState.NOT_COLLECTED,
    AbstentionReason.SCHEMA_VALIDATION_FAILED: ValueState.PARSING_FAILED,
}


def collect_gerp(ctx: RunContext) -> dict[str, Any]:
    deps: DiscoveryDeps = ctx.deps
    req = _request(ctx)
    if SignalFamily.GERP not in req.signal_families:
        return {"skipped": "gerp not requested"}
    pack = deps.pack
    market = pack.market(req.market)
    gateway = deps.platform.gateway
    answer_prompt = pack.prompt("gerp_answer")
    extract_prompt = pack.prompt("gerp_extraction")
    lexicon = deps.resolver.lexicon()
    repeats = repeats_for(pack, req)
    counts: dict[str, int] = {}
    injection = 0
    for q in pack.queries_for(req.market, req.tier, req.language):
        for r in range(repeats):
            ctx.check_controls()
            with ctx.span("GERP observation", {"query.id": q.query_id, "gerp.repeat_index": r}):
                result = gateway.invoke(
                    capability_id="gerp.observe",
                    prompt=answer_prompt,
                    variables={
                        "market": req.market,
                        "market_name": market.name,
                        "language": q.language,
                        "device": (req.device or market.default_device).value,
                        "query_text": q.text,
                        "query_id": q.query_id,
                        "repeat_index": r,
                    },
                    output_model=GerpAnswerOutput,
                    run=ctx,
                )
                base = _base_obs(ctx, pack, req, q, SignalFamily.GERP, r)
                meta = {
                    "provider": f"model_gateway/{result.provider}",
                    "endpoint": "chat.completions",
                    "prompt_id": result.prompt_id,
                    "prompt_version": result.prompt_version,
                    "model_id": result.model_id,
                    "cost_usd": result.cost_usd,
                    "simulated": result.simulated,
                    "retry_count": result.retries,
                    "parser_version": f"{extract_prompt.prompt_id}@{extract_prompt.version}",
                }
                if not result.ok:
                    state = _ABSTAIN_STATE.get(result.abstention_reason, ValueState.PROVIDER_ERROR)
                    obs = Observation(**base, **meta, status=state, error=f"abstained: {result.abstention_reason}")
                    deps.repo.upsert_observation(obs)
                    counts[state.value] = counts.get(state.value, 0) + 1
                    continue
                artifact = deps.platform.evidence.persist_raw(
                    (result.raw_response or "").encode(), run_id=ctx.run_id, namespace="raw/gerp"
                )
                answer = result.output or {}
                with ctx.span("Citation extraction", {"query.id": q.query_id}):
                    extraction = gateway.invoke(
                        capability_id="gerp.extract",
                        prompt=extract_prompt,
                        variables={"answer_text": answer["answer_text"], "lexicon": lexicon},
                        output_model=GerpExtractionOutput,
                        run=ctx,
                    )
                flags = []
                status = ValueState.OBSERVED_VALUE
                if extraction.injection_findings:
                    flags.append("PROMPT_INJECTION_SUSPECTED")
                    injection += 1
                if not extraction.ok:
                    flags.append("EXTRACTION_ABSTAINED")
                    status = ValueState.PARSING_FAILED
                obs = Observation(
                    **base,
                    **meta,
                    status=status,
                    raw_artifact_uri=artifact.uri,
                    content_hash=artifact.sha256,
                    quality_flags=flags,
                    payload={
                        "answer_text": answer["answer_text"],
                        "citations": answer.get("citations", []),
                        "extraction": extraction.output or {},
                        "extraction_meta": {
                            "model_id": extraction.model_id,
                            "prompt_id": extraction.prompt_id,
                            "prompt_version": extraction.prompt_version,
                            "agent_run_id": extraction.agent_run_id,
                            "abstention_reason": extraction.abstention_reason,
                            "injection_findings": extraction.injection_findings,
                        },
                    },
                )
                deps.repo.upsert_observation(obs)
                counts[status.value] = counts.get(status.value, 0) + 1
    return {
        "observations": sum(counts.values()),
        "by_status": counts,
        "repeats": repeats,
        "injection_flagged_answers": injection,
        "model_id": gateway.default_model,
    }
