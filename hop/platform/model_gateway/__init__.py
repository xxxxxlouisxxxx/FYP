"""Governed model gateway (spec 5.2). Agents never call models directly.

Every call: kill-switch check -> capability/tool policy -> model allowlist -> prompt rendering with
instruction/data separation -> injection scan -> size limit -> redaction -> budget reservation ->
adapter call with timeout and retry -> JSON parse -> schema validation -> audit metadata.
Any failure after policy checks produces a structured abstention, never fabricated output.
"""

from __future__ import annotations

import contextvars
import json
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, ValidationError

from hop.platform.audit import AuditLog
from hop.platform.common_contracts import (
    ActorType,
    AgentRun,
    AgentRunStatus,
    Contract,
    canonical_json,
    sha256_hex,
    utcnow,
)
from hop.platform.evidence_service import EvidenceService
from hop.platform.observability import Telemetry, current_span_id, current_trace_id
from hop.platform.policy_engine import KillSwitch, PolicyEngine
from hop.platform.policy_engine.content_safety import detect_injection, redact, wrap_untrusted
from hop.platform.storage.db import AgentRunRow, Store
from hop.platform.workflow_runtime.errors import PermanentError, TransientError
from hop.platform.workflow_runtime.retry import RetryPolicy, retry_call


class PromptTemplate(Contract):
    prompt_id: str
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    purpose: str
    task: str = Field(description="adapter task hint, e.g. gerp_answer, gerp_extraction, explanation")
    system: str
    user: str
    untrusted_variables: list[str] = Field(default_factory=list)
    output_schema: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ModelSpec(Contract):
    model_id: str
    provider: Literal["mock", "openai_compatible"]
    cost_per_1k_input_usd: float = Field(ge=0)
    cost_per_1k_output_usd: float = Field(ge=0)
    max_context_chars: int = 48000
    simulated: bool = False


class AbstentionReason(StrEnum):
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    INPUT_TOO_LARGE = "INPUT_TOO_LARGE"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    SCHEMA_VALIDATION_FAILED = "SCHEMA_VALIDATION_FAILED"
    MODEL_ABSTAINED = "MODEL_ABSTAINED"
    NO_ADAPTER = "NO_ADAPTER"


@dataclass
class ModelCall:
    capability_id: str
    model_id: str
    task: str
    messages: list[dict[str, str]]
    variables: dict[str, Any]
    parameters: dict[str, Any]
    max_output_tokens: int
    timeout_s: float
    run_id: str | None = None


@dataclass
class RawCompletion:
    text: str
    tokens_in: int
    tokens_out: int
    provider_request_id: str | None = None


class ModelAdapter(Protocol):
    provider: str

    def complete(self, call: ModelCall) -> RawCompletion: ...


class ModelTransientError(TransientError):
    pass


class ModelPermanentError(PermanentError):
    pass


class GatewayResult(BaseModel):
    status: Literal["OK", "ABSTAINED"]
    output: dict[str, Any] | None = None
    abstention_reason: AbstentionReason | None = None
    detail: str | None = None
    capability_id: str
    model_id: str | None = None
    provider: str | None = None
    prompt_id: str
    prompt_version: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    simulated: bool = False
    latency_ms: float = 0.0
    retries: int = 0
    request_hash: str | None = None
    response_hash: str | None = None
    raw_response: str | None = Field(default=None, exclude=True)
    payload_uri: str | None = None
    injection_findings: list[str] = Field(default_factory=list)
    agent_run_id: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "OK"


class RunBudget(Protocol):
    """Implemented by the workflow RunContext; lets the gateway reserve and record spend."""

    run_id: str

    @property
    def budget(self) -> Any: ...

    def spend(self, amount_usd: float, **meta: Any) -> None: ...


@dataclass
class StandaloneBudget:
    """Budget holder for model calls outside a workflow run (e.g. evaluation)."""

    limit_usd: float
    run_id: str | None = None
    spent: list[float] = field(default_factory=list)

    @property
    def budget(self) -> StandaloneBudget:
        return self

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.limit_usd - sum(self.spent))

    def spend(self, amount_usd: float, **meta: Any) -> None:
        self.spent.append(amount_usd)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _render(template: str, variables: dict[str, Any]) -> str:
    class _Safe(dict[str, Any]):
        def __missing__(self, key: str) -> str:
            raise KeyError(f"prompt variable '{key}' not supplied")

    return template.format_map(_Safe(variables))


class ModelGateway:
    def __init__(
        self,
        *,
        policy: PolicyEngine,
        kill_switch: KillSwitch,
        telemetry: Telemetry,
        evidence: EvidenceService,
        audit: AuditLog,
        store: Store,
        models: dict[str, ModelSpec],
        adapters: dict[str, ModelAdapter],
        default_model: str,
        retry: RetryPolicy | None = None,
        timeout_s: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.policy = policy
        self.kill_switch = kill_switch
        self.telemetry = telemetry
        self.evidence = evidence
        self.audit = audit
        self.store = store
        self.models = models
        self.adapters = adapters
        self.default_model = default_model
        self.retry = retry or RetryPolicy(max_attempts=2, base_delay_s=0.05, max_delay_s=0.5)
        self.timeout_s = timeout_s
        self.sleep = sleep
        policy.global_model_allowlist = set(models)

    def render(self, prompt: PromptTemplate, variables: dict[str, Any]) -> tuple[list[dict[str, str]], list[str]]:
        rendered: dict[str, Any] = {}
        findings: list[str] = []
        for key, value in variables.items():
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
            if key in prompt.untrusted_variables:
                findings.extend(f"{key}:{f.pattern}" for f in detect_injection(text))
                text = wrap_untrusted(text, key)
            rendered[key] = text
        messages = [
            {"role": "system", "content": prompt.system.strip()},
            {"role": "user", "content": redact(_render(prompt.user, rendered))},
        ]
        return messages, findings

    def invoke(
        self,
        *,
        capability_id: str,
        prompt: PromptTemplate,
        variables: dict[str, Any],
        output_model: type[BaseModel],
        run: RunBudget | None = None,
        model_id: str | None = None,
    ) -> GatewayResult:
        model_id = model_id or self.default_model
        run_id = getattr(run, "run_id", None)
        started = utcnow()
        t0 = time.perf_counter()
        manifest = self.policy.registry.get(capability_id)
        with self.telemetry.span(
            "Model call",
            {
                "capability.id": capability_id,
                "capability.version": manifest.version,
                "model.id": model_id,
                "prompt.id": prompt.prompt_id,
                "prompt.version": prompt.version,
                "run.id": run_id,
            },
        ) as span:
            self.kill_switch.check()
            self.policy.enforce_tool(capability_id, "model.invoke", run_id)
            decision = self.policy.check_model(capability_id, model_id, run_id)
            if not decision.allowed:
                from hop.platform.policy_engine import PolicyViolation

                raise PolicyViolation(decision)
            spec = self.models[model_id]
            base = {
                "capability_id": capability_id,
                "model_id": model_id,
                "provider": spec.provider,
                "prompt_id": prompt.prompt_id,
                "prompt_version": prompt.version,
                "simulated": spec.simulated,
            }
            with self.telemetry.span("Prompt rendering", {"prompt.id": prompt.prompt_id}):
                messages, findings = self.render(prompt, variables)
            input_chars = sum(len(m["content"]) for m in messages)
            max_chars = manifest.model_policy.max_input_chars if manifest.model_policy else spec.max_context_chars
            request_hash = sha256_hex(canonical_json(messages))
            span.set_attribute("request.hash", request_hash)
            span.set_attribute("input.chars", input_chars)
            if findings:
                span.set_attribute("content.injection_findings", findings)

            def abstain(reason: AbstentionReason, detail: str, **extra: Any) -> GatewayResult:
                span.set_attribute("model.abstained", reason.value)
                result = GatewayResult(
                    status="ABSTAINED",
                    abstention_reason=reason,
                    detail=detail,
                    request_hash=request_hash,
                    injection_findings=findings,
                    latency_ms=round((time.perf_counter() - t0) * 1000, 2),
                    **base,
                    **extra,
                )
                return self._record(result, manifest, started, run_id)

            if input_chars > max_chars:
                return abstain(AbstentionReason.INPUT_TOO_LARGE, f"{input_chars} > {max_chars} chars")
            max_out = manifest.model_policy.max_output_tokens if manifest.model_policy else 800
            tokens_in_est = estimate_tokens("".join(m["content"] for m in messages))
            est_cost = self._cost(spec, tokens_in_est, max_out)
            if run is not None:
                budget_decision = self.policy.check_budget(capability_id, est_cost, run.budget.remaining_usd, run_id)
                if not budget_decision.allowed:
                    return abstain(AbstentionReason.BUDGET_EXCEEDED, budget_decision.reason)
            adapter = self.adapters.get(spec.provider)
            if adapter is None:
                return abstain(AbstentionReason.NO_ADAPTER, f"no adapter for provider {spec.provider}")
            call = ModelCall(
                capability_id=capability_id,
                model_id=model_id,
                task=prompt.task,
                messages=messages,
                variables=variables,
                parameters=prompt.parameters,
                max_output_tokens=max_out,
                timeout_s=min(self.timeout_s, manifest.max_duration_seconds),
                run_id=run_id,
            )
            retries = 0

            def on_retry(attempt: int, exc: BaseException, delay: float) -> None:
                nonlocal retries
                retries = attempt

            try:
                completion = retry_call(
                    lambda: self._call_with_timeout(adapter, call), self.retry, sleep=self.sleep, on_retry=on_retry
                )
            except TimeoutError as exc:
                return abstain(AbstentionReason.TIMEOUT, str(exc), retries=retries)
            except (TransientError, PermanentError) as exc:
                return abstain(AbstentionReason.PROVIDER_UNAVAILABLE, str(exc), retries=retries)

            cost = self._cost(spec, completion.tokens_in, completion.tokens_out)
            if run is not None:
                run.spend(
                    cost,
                    category="model",
                    provider=spec.provider,
                    capability_id=capability_id,
                    units=completion.tokens_in + completion.tokens_out,
                    unit="tokens",
                    simulated=spec.simulated,
                )
            response_hash = sha256_hex(completion.text)
            payload_uri = self.evidence.persist_raw(
                canonical_json({"request": messages, "response": completion.text, "model_id": model_id}),
                run_id=run_id,
                namespace="protected/model_calls",
                classification="CONFIDENTIAL",
            ).uri
            metered = {
                "tokens_in": completion.tokens_in,
                "tokens_out": completion.tokens_out,
                "cost_usd": cost,
                "retries": retries,
                "response_hash": response_hash,
                "payload_uri": payload_uri,
                "raw_response": completion.text,
            }
            span.set_attribute("tokens.in", completion.tokens_in)
            span.set_attribute("tokens.out", completion.tokens_out)
            span.set_attribute("cost.usd", cost)
            span.set_attribute("retry.count", retries)
            try:
                parsed = json.loads(completion.text)
            except json.JSONDecodeError as exc:
                return abstain(AbstentionReason.SCHEMA_VALIDATION_FAILED, f"non-JSON output: {exc}", **metered)
            if isinstance(parsed, dict) and parsed.get("abstain") is True:
                return abstain(AbstentionReason.MODEL_ABSTAINED, str(parsed.get("reason", "")), **metered)
            try:
                output = output_model.model_validate(parsed).model_dump(mode="json")
            except ValidationError as exc:
                return abstain(AbstentionReason.SCHEMA_VALIDATION_FAILED, str(exc)[:500], **metered)
            result = GatewayResult(
                status="OK",
                output=output,
                request_hash=request_hash,
                injection_findings=findings,
                latency_ms=round((time.perf_counter() - t0) * 1000, 2),
                **base,
                **metered,
            )
            return self._record(result, manifest, started, run_id)

    def _call_with_timeout(self, adapter: ModelAdapter, call: ModelCall) -> RawCompletion:
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(contextvars.copy_context().run, adapter.complete, call)
        try:
            return future.result(timeout=call.timeout_s)
        except FutureTimeout as exc:
            raise TimeoutError(f"model call exceeded {call.timeout_s}s") from exc
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _cost(spec: ModelSpec, tokens_in: int, tokens_out: int) -> float:
        return round(tokens_in / 1000 * spec.cost_per_1k_input_usd + tokens_out / 1000 * spec.cost_per_1k_output_usd, 8)

    def _record(self, result: GatewayResult, manifest: Any, started: Any, run_id: str | None) -> GatewayResult:
        agent_run = AgentRun(
            run_id=run_id,
            capability_id=result.capability_id,
            capability_version=manifest.version,
            purpose=manifest.purpose,
            status=AgentRunStatus.SUCCEEDED if result.ok else AgentRunStatus.ABSTAINED,
            started_at=started,
            ended_at=utcnow(),
            latency_ms=result.latency_ms,
            steps=1,
            max_steps=manifest.max_steps,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost_usd=result.cost_usd,
            simulated=result.simulated,
            model_id=result.model_id,
            provider=result.provider,
            prompt_id=result.prompt_id,
            prompt_version=result.prompt_version,
            request_hash=result.request_hash,
            response_hash=result.response_hash,
            payload_uri=result.payload_uri,
            abstention_reason=result.abstention_reason.value if result.abstention_reason else None,
            retry_count=result.retries,
            trace_id=current_trace_id(),
            span_id=current_span_id(),
        )
        with self.store.session() as s:
            s.add(
                AgentRunRow(
                    agent_run_id=agent_run.agent_run_id,
                    run_id=run_id,
                    capability_id=agent_run.capability_id,
                    status=agent_run.status.value,
                    body=agent_run.model_dump(mode="json"),
                )
            )
        if not result.ok:
            self.audit.record(
                actor=result.capability_id,
                actor_type=ActorType.AGENT,
                action="model.abstained",
                resource_type="agent_run",
                resource_id=agent_run.agent_run_id,
                outcome="FAILURE",
                details={"reason": result.abstention_reason, "detail": (result.detail or "")[:300]},
                trace_id=agent_run.trace_id,
            )
        return result.model_copy(update={"agent_run_id": agent_run.agent_run_id})
