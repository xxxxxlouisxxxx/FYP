"""Composition root: wires platform services, a domain pack and the Opportunity Intelligence product.

This is the only module (with the CLI, API and dashboard entry points) that knows about all three
layers. ``hop.platform`` never imports from ``hop.products`` or a domain pack.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from hop.platform.domain_registry import DomainPack, load_domain_pack
from hop.platform.entity_resolution import EntityResolver
from hop.platform.integrations import DemandProvider, SerpProvider
from hop.platform.integrations.sandbox import SandboxDemandProvider, SandboxSerpProvider, gerp_fixture_lookup
from hop.platform.services import PlatformServices, build_platform
from hop.platform.settings import Settings
from hop.products.opportunity_intelligence.config import OpportunityConfig, load_opportunity_config
from hop.products.opportunity_intelligence.deps import DiscoveryDeps
from hop.products.opportunity_intelligence.opportunity_lifecycle import OpportunityLifecycle
from hop.products.opportunity_intelligence.repository import OpportunityRepository
from hop.products.opportunity_intelligence.tools import build_tool_registry

PRODUCT_CAPABILITIES = Path(__file__).parent / "products" / "opportunity_intelligence" / "capabilities"


class ConfigurationError(RuntimeError):
    pass


def provider_mode(settings: Settings, requested: str = "auto") -> str:
    choice = requested if requested != "auto" else settings.serp_provider
    if choice == "auto":
        return "dataforseo" if settings.dataforseo_configured else "sandbox"
    if choice == "dataforseo" and not settings.dataforseo_configured:
        raise ConfigurationError("DataForSEO requested but DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD are not set")
    if choice not in ("sandbox", "dataforseo"):
        raise ConfigurationError(f"unknown provider {choice!r}; use auto, sandbox or dataforseo")
    return choice


@dataclass
class App:
    settings: Settings
    platform: PlatformServices
    pack: DomainPack
    config: OpportunityConfig

    @cached_property
    def repo(self) -> OpportunityRepository:
        return OpportunityRepository(self.platform.store)

    @cached_property
    def resolver(self) -> EntityResolver:
        return EntityResolver(self.pack.entities)

    @cached_property
    def lifecycle(self) -> OpportunityLifecycle:
        return OpportunityLifecycle(self.platform, self.repo)

    def discovery_deps(self, requested_provider: str = "auto") -> DiscoveryDeps:
        mode = provider_mode(self.settings, requested_provider)
        platform = self.platform
        sandbox = self.pack.sandbox_dir

        def serp(run_id: str) -> SerpProvider:
            if mode == "dataforseo":
                from hop.platform.integrations.dataforseo import DataForSEOSerpProvider

                return DataForSEOSerpProvider(
                    policy=platform.policy, kill_switch=platform.kill_switch, run_id=run_id, **self._dfs_credentials()
                )
            return SandboxSerpProvider(
                _require(sandbox), policy=platform.policy, kill_switch=platform.kill_switch, run_id=run_id
            )

        def demand(run_id: str) -> DemandProvider:
            if mode == "dataforseo":
                from hop.platform.integrations.dataforseo import DataForSEODemandProvider

                return DataForSEODemandProvider(
                    policy=platform.policy, kill_switch=platform.kill_switch, run_id=run_id, **self._dfs_credentials()
                )
            return SandboxDemandProvider(
                _require(sandbox), policy=platform.policy, kill_switch=platform.kill_switch, run_id=run_id
            )

        return DiscoveryDeps(
            platform=platform,
            pack=self.pack,
            config=self.config,
            repo=self.repo,
            resolver=self.resolver,
            tools=build_tool_registry(platform.evidence, self.pack),
            serp_provider=serp,
            demand_provider=demand,
            provider_mode=mode,
        )

    def _dfs_credentials(self) -> dict[str, str]:
        s = self.settings
        assert s.dataforseo_login and s.dataforseo_password
        return {"login": s.dataforseo_login, "password": s.dataforseo_password.get_secret_value()}


def _require(path: Path | None) -> Path:
    if path is None or not path.exists():
        raise ConfigurationError("domain pack has no sandbox fixtures; configure a real provider")
    return path


def build_app(settings: Settings | None = None, *, pack_id: str | None = None, sleep=None) -> App:  # noqa: ANN001
    settings = settings or Settings.from_env()
    pack = load_domain_pack(settings.domain_packs_dir, pack_id or settings.default_domain_pack)
    config = load_opportunity_config(pack)
    lookup = gerp_fixture_lookup(pack.sandbox_dir) if pack.sandbox_dir else None
    platform = build_platform(
        settings, capability_dirs=[PRODUCT_CAPABILITIES], model_fixture_lookup=lookup, sleep=sleep
    )
    return App(settings=settings, platform=platform, pack=pack, config=config)
