"""Deterministic sandbox provider replaying recorded DataForSEO-shaped payloads from a fixture directory.

Fixture layout (inside a domain pack's ``sandbox`` directory)::

    {market}/serp/{query_id}.json          DataForSEO SERP live/advanced response
    {market}/demand/search_volume_{lang}.json   DataForSEO search-volume response
    {market}/gerp/{query_id}.json          recorded generative-engine answers

An optional top-level ``_sandbox`` object controls simulation (``transient_failures``,
``provider_error``) and is stripped before the payload is returned, so the raw payload is exactly the
recorded provider response.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hop.platform.integrations import ProviderPermanentError, ProviderResponse, ProviderTransientError
from hop.platform.integrations.dataforseo import SERP_ENDPOINT, VOLUME_ENDPOINT, _check_envelope
from hop.platform.policy_engine import KillSwitch, PolicyEngine


class _SandboxBase:
    name = "sandbox"
    capability_id = ""
    unit_cost_usd = 0.0

    def __init__(self, fixtures_dir: Path, *, policy: PolicyEngine, kill_switch: KillSwitch, run_id: str | None = None):
        self.fixtures_dir = Path(fixtures_dir)
        self.policy = policy
        self.kill_switch = kill_switch
        self.run_id = run_id
        self._attempts: dict[str, int] = {}

    def _load(self, path: Path) -> tuple[bytes | None, dict[str, Any]]:
        self.kill_switch.check()
        self.policy.enforce_tool(self.capability_id, "provider.fixture_read", self.run_id)
        if not path.exists():
            return None, {}
        doc = json.loads(path.read_text(encoding="utf-8"))
        control = doc.pop("_sandbox", {}) or {}
        key = str(path)
        self._attempts[key] = self._attempts.get(key, 0) + 1
        if self._attempts[key] <= int(control.get("transient_failures", 0)):
            raise ProviderTransientError(f"sandbox simulated transient failure for {path.name}")
        raw = json.dumps(doc, ensure_ascii=False, indent=1).encode()
        return raw, control


class SandboxSerpProvider(_SandboxBase):
    capability_id = "sandbox.serp.collect"
    unit_cost_usd = 0.002

    def fetch_serp(
        self,
        *,
        market: str,
        query_id: str,
        keyword: str,
        location_code: int,
        language_code: str,
        device: str,
        depth: int,
    ) -> ProviderResponse:
        raw, _ = self._load(self.fixtures_dir / market / "serp" / f"{query_id}.json")
        if raw is None:
            return ProviderResponse(self.name, SERP_ENDPOINT, None, None, 0.0, True, "not_collected", "no fixture")
        try:
            task = _check_envelope(json.loads(raw))
        except ProviderPermanentError as exc:
            return ProviderResponse(self.name, SERP_ENDPOINT, raw, None, 0.0, True, "provider_error", str(exc))
        return ProviderResponse(
            self.name, SERP_ENDPOINT, raw, task.get("id"), float(task.get("cost") or self.unit_cost_usd), True, "ok"
        )


class SandboxDemandProvider(_SandboxBase):
    capability_id = "sandbox.demand.collect"
    unit_cost_usd = 0.075

    def fetch_search_volume(
        self, *, market: str, keywords: list[str], location_code: int, language_code: str
    ) -> ProviderResponse:
        raw, _ = self._load(self.fixtures_dir / market / "demand" / f"search_volume_{language_code}.json")
        if raw is None:
            return ProviderResponse(self.name, VOLUME_ENDPOINT, None, None, 0.0, True, "not_collected", "no fixture")
        try:
            task = _check_envelope(json.loads(raw))
        except ProviderPermanentError as exc:
            return ProviderResponse(self.name, VOLUME_ENDPOINT, raw, None, 0.0, True, "provider_error", str(exc))
        return ProviderResponse(
            self.name, VOLUME_ENDPOINT, raw, task.get("id"), float(task.get("cost") or self.unit_cost_usd), True, "ok"
        )


def gerp_fixture_lookup(fixtures_dir: Path):  # noqa: ANN201 - returns a closure
    """Build the lookup used by the mock model adapter to replay recorded generative-engine answers."""

    root = Path(fixtures_dir)

    def lookup(variables: dict[str, Any]) -> dict[str, Any] | None:
        path = root / str(variables.get("market")) / "gerp" / f"{variables.get('query_id')}.json"
        if not path.exists():
            return None
        doc = json.loads(path.read_text(encoding="utf-8"))
        repeat = int(variables.get("repeat_index", 0))
        for answer in doc.get("answers", []):
            if int(answer.get("repeat_index", -1)) == repeat:
                return answer
        return None

    return lookup
