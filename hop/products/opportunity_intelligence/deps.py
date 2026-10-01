"""Dependencies injected into the discovery workflow activities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from hop.platform.domain_registry import DomainPack
from hop.platform.entity_resolution import EntityResolver
from hop.platform.integrations import DemandProvider, SerpProvider
from hop.platform.policy_engine.tools import ToolRegistry
from hop.platform.services import PlatformServices
from hop.products.opportunity_intelligence.config import OpportunityConfig
from hop.products.opportunity_intelligence.repository import OpportunityRepository


@dataclass
class DiscoveryDeps:
    platform: PlatformServices
    pack: DomainPack
    config: OpportunityConfig
    repo: OpportunityRepository
    resolver: EntityResolver
    tools: ToolRegistry
    serp_provider: Callable[[str], SerpProvider]
    demand_provider: Callable[[str], DemandProvider]
    provider_mode: str


def step_output(ctx: Any, step: str) -> dict[str, Any]:
    """Output of an earlier activity, read from its checkpoint so resumed runs see the same data."""
    return ctx.runtime.checkpoints(ctx.run_id).get(step, {})
