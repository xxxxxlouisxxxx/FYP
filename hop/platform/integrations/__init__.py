"""Provider adapters behind explicit contracts (governed extension point ``provider_adapter``)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from hop.platform.workflow_runtime.errors import PermanentError, TransientError


class ProviderTransientError(TransientError):
    pass


class ProviderPermanentError(PermanentError):
    pass


@dataclass(frozen=True)
class ProviderResponse:
    provider: str
    endpoint: str
    raw: bytes | None
    task_id: str | None
    cost_usd: float
    simulated: bool
    status: str  # "ok" | "provider_error" | "not_collected"
    error: str | None = None


class SerpProvider(Protocol):
    name: str
    capability_id: str
    unit_cost_usd: float

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
    ) -> ProviderResponse: ...


class DemandProvider(Protocol):
    name: str
    capability_id: str
    unit_cost_usd: float

    def fetch_search_volume(
        self, *, market: str, keywords: list[str], location_code: int, language_code: str
    ) -> ProviderResponse: ...
