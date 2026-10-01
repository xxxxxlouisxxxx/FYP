"""Capability registry (spec 5.4 / 6.2). Every collector, agent, rule set, evaluator and exporter is a
registered, versioned capability with an owner, permissions, network policy and budgets."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, ValidationError, field_validator

from hop.platform.common_contracts import Contract
from hop.platform.storage.db import SettingRow, Store

REVOKED_KEY = "capability_registry.revoked"


class CapabilityStatus(StrEnum):
    DRAFT = "draft"
    TESTED = "tested"
    APPROVED = "approved"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class CapabilityKind(StrEnum):
    COLLECTOR = "collector"
    AGENT = "agent"
    SERVICE = "service"
    RULE = "rule"
    EVALUATOR = "evaluator"
    EXPORTER = "exporter"


class NetworkPolicy(Contract):
    outbound_allowlist: list[str] = Field(default_factory=list)


class ModelPolicy(Contract):
    allowed_models: list[str] = Field(default_factory=list)
    max_input_chars: int = 24000
    max_output_tokens: int = 1200


class CapabilityManifest(Contract):
    capability_id: str = Field(pattern=r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    kind: CapabilityKind
    owner: str
    status: CapabilityStatus
    purpose: str
    input_schema: str
    output_schema: str
    permissions: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    evidence_classes: list[str] = Field(default_factory=list)
    network_policy: NetworkPolicy = Field(default_factory=NetworkPolicy)
    model_policy: ModelPolicy | None = None
    max_steps: int = Field(default=20, ge=1, le=1000)
    max_duration_seconds: float = Field(default=300, gt=0)
    max_cost_usd: float = Field(default=1.0, ge=0)
    abstain_when: list[str] = Field(default_factory=list)
    human_review: str | None = None
    evaluation_suite: str | None = None
    slo: dict[str, Any] = Field(default_factory=dict)
    cost_model: dict[str, Any] = Field(default_factory=dict)
    documentation: dict[str, str] = Field(default_factory=dict)

    @field_validator("allowed_tools")
    @classmethod
    def _no_wildcards(cls, tools: list[str]) -> list[str]:
        if any("*" in t for t in tools):
            raise ValueError("wildcard tool grants are not permitted (deny-by-default)")
        return tools


class UnknownCapabilityError(KeyError):
    pass


class CapabilityRegistry:
    def __init__(self, store: Store | None = None) -> None:
        self._manifests: dict[str, CapabilityManifest] = {}
        self._sources: dict[str, str] = {}
        self.store = store

    def load_dir(self, directory: Path) -> list[CapabilityManifest]:
        loaded = []
        for path in sorted(Path(directory).glob("*.yaml")):
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            try:
                manifest = CapabilityManifest.model_validate(raw)
            except ValidationError as exc:
                raise ValueError(f"invalid capability manifest {path}: {exc}") from exc
            self.register(manifest, source=str(path))
            loaded.append(manifest)
        return loaded

    def register(self, manifest: CapabilityManifest, source: str = "code") -> None:
        if manifest.capability_id in self._manifests:
            raise ValueError(f"duplicate capability {manifest.capability_id}")
        self._manifests[manifest.capability_id] = manifest
        self._sources[manifest.capability_id] = source

    def get(self, capability_id: str) -> CapabilityManifest:
        try:
            return self._manifests[capability_id]
        except KeyError as exc:
            raise UnknownCapabilityError(capability_id) from exc

    def all(self) -> list[CapabilityManifest]:
        return sorted(self._manifests.values(), key=lambda m: m.capability_id)

    def source(self, capability_id: str) -> str:
        return self._sources.get(capability_id, "?")

    # revocation without redeploy ------------------------------------------------------------
    def revoked(self) -> dict[str, str]:
        if self.store is None:
            return {}
        with self.store.session() as s:
            row = s.get(SettingRow, REVOKED_KEY)
            return dict(row.value) if row else {}

    def revoke(self, capability_id: str, reason: str) -> None:
        self.get(capability_id)
        self._set_revoked({**self.revoked(), capability_id: reason})

    def reinstate(self, capability_id: str) -> None:
        current = self.revoked()
        current.pop(capability_id, None)
        self._set_revoked(current)

    def _set_revoked(self, value: dict[str, str]) -> None:
        if self.store is None:
            raise RuntimeError("registry has no store; cannot persist revocation")
        with self.store.session() as s:
            s.merge(SettingRow(key=REVOKED_KEY, value=value))

    def executable_status(self, capability_id: str, env: str) -> tuple[bool, str]:
        try:
            manifest = self.get(capability_id)
        except UnknownCapabilityError:
            return False, "capability not registered"
        revoked = self.revoked()
        if capability_id in revoked:
            return False, f"capability revoked: {revoked[capability_id]}"
        if manifest.status == CapabilityStatus.APPROVED:
            return True, "approved"
        if manifest.status == CapabilityStatus.TESTED and env != "production":
            return True, "tested (non-production only)"
        return False, f"capability status {manifest.status.value} is not executable in {env}"


def load_registry(dirs: Iterable[Path], store: Store | None = None) -> CapabilityRegistry:
    registry = CapabilityRegistry(store)
    for d in dirs:
        registry.load_dir(d)
    return registry
