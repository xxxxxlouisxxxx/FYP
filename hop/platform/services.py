"""Assembly of platform services from settings. Domain- and product-agnostic."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hop.platform.audit import AuditLog
from hop.platform.capability_registry import CapabilityRegistry, load_registry
from hop.platform.evidence_service import EvidenceService, LocalObjectStore
from hop.platform.model_gateway import ModelAdapter, ModelGateway, ModelSpec
from hop.platform.model_gateway.mock import MockModelAdapter
from hop.platform.observability import CostRecorder, Telemetry
from hop.platform.policy_engine import KillSwitch, PolicyEngine
from hop.platform.settings import Settings
from hop.platform.storage.db import Store
from hop.platform.workflow_runtime import WorkflowRuntime

PLATFORM_MANIFESTS = Path(__file__).parent / "capability_registry" / "manifests"

MOCK_MODEL = ModelSpec(
    model_id="mock-gerp-1",
    provider="mock",
    cost_per_1k_input_usd=0.00015,
    cost_per_1k_output_usd=0.0006,
    simulated=True,
)


@dataclass
class PlatformServices:
    settings: Settings
    store: Store
    objects: LocalObjectStore
    evidence: EvidenceService
    audit: AuditLog
    telemetry: Telemetry
    costs: CostRecorder
    registry: CapabilityRegistry
    policy: PolicyEngine
    kill_switch: KillSwitch
    gateway: ModelGateway
    runtime: WorkflowRuntime


def build_platform(
    settings: Settings,
    *,
    capability_dirs: Iterable[Path] = (),
    model_fixture_lookup: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> PlatformServices:
    store = Store(settings.database_url)
    store.init()
    objects = LocalObjectStore(settings.object_store_dir)
    evidence = EvidenceService(store, objects)
    audit = AuditLog(store, settings.tenant_id)
    telemetry = Telemetry(store, tenant_id=settings.tenant_id, console=settings.otel_console)
    costs = CostRecorder(store)
    registry = load_registry([PLATFORM_MANIFESTS, *capability_dirs], store)
    policy = PolicyEngine(registry, store, audit, env=settings.env)
    kill_switch = KillSwitch(store, env_engaged=settings.kill_switch)

    models: dict[str, ModelSpec] = {MOCK_MODEL.model_id: MOCK_MODEL}
    adapters: dict[str, ModelAdapter] = {"mock": MockModelAdapter(model_fixture_lookup)}
    default_model = MOCK_MODEL.model_id
    use_openai = settings.model_provider == "openai" or (
        settings.model_provider == "auto" and settings.openai_configured
    )
    if use_openai and settings.openai_api_key is not None:
        from hop.platform.model_gateway.openai_compat import OpenAICompatibleAdapter

        models[settings.openai_model] = ModelSpec(
            model_id=settings.openai_model,
            provider="openai_compatible",
            cost_per_1k_input_usd=0.00015,
            cost_per_1k_output_usd=0.0006,
        )
        adapters["openai_compatible"] = OpenAICompatibleAdapter(
            policy=policy,
            kill_switch=kill_switch,
            api_key=settings.openai_api_key.get_secret_value(),
            base_url=settings.openai_base_url,
        )
        default_model = settings.openai_model
    extra = {"sleep": sleep} if sleep else {}
    gateway = ModelGateway(
        policy=policy,
        kill_switch=kill_switch,
        telemetry=telemetry,
        evidence=evidence,
        audit=audit,
        store=store,
        models=models,
        adapters=adapters,
        default_model=default_model,
        **extra,
    )
    runtime = WorkflowRuntime(
        store=store,
        telemetry=telemetry,
        kill_switch=kill_switch,
        costs=costs,
        audit=audit,
        tenant_id=settings.tenant_id,
        run_timeout_s=settings.run_timeout_s,
        max_activity_attempts=settings.max_activity_attempts_per_run,
        **extra,
    )
    return PlatformServices(
        settings=settings,
        store=store,
        objects=objects,
        evidence=evidence,
        audit=audit,
        telemetry=telemetry,
        costs=costs,
        registry=registry,
        policy=policy,
        kill_switch=kill_switch,
        gateway=gateway,
        runtime=runtime,
    )
