from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from hop.bootstrap import App, build_app
from hop.platform.common_contracts import CollectionRequest, CollectionRun
from hop.platform.settings import Settings
from hop.products.opportunity_intelligence.pipeline import start_discovery

REPO_ROOT = Path(__file__).resolve().parents[1]


def make_settings(data_dir: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "data_dir": data_dir,
        "database_url": f"sqlite:///{data_dir / 'hop.db'}",
        "object_store_dir": data_dir / "objects",
        "domain_packs_dir": REPO_ROOT / "domain_packs",
        "serp_provider": "sandbox",
        "model_provider": "mock",
        "dataforseo_login": None,
        "dataforseo_password": None,
        "openai_api_key": None,
        "kill_switch": False,
    }
    values.update(overrides)
    return Settings.from_env(**values)


def make_app(data_dir: Path, **overrides: object) -> App:
    return build_app(make_settings(data_dir, **overrides), sleep=lambda _s: None)


def hk_request(**overrides: object) -> CollectionRequest:
    values: dict[str, object] = {"domain_pack": "sports-footwear", "market": "HK", "tier": "A"}
    values.update(overrides)
    return CollectionRequest(**values)


@dataclass
class Discovery:
    app: App
    run: CollectionRun
    data_dir: Path


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD", "OPENAI_API_KEY", "HOP_KILL_SWITCH", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def app(tmp_path: Path) -> App:
    return make_app(tmp_path)


@pytest.fixture(scope="session")
def discovery(tmp_path_factory: pytest.TempPathFactory) -> Discovery:
    """One sandbox HK tier-A run shared by read-only tests."""
    data_dir = tmp_path_factory.mktemp("discovery")
    application = make_app(data_dir)
    run = start_discovery(application.discovery_deps(), hk_request(), force_new=True)
    return Discovery(application, run, data_dir)


@pytest.fixture
def fresh_discovery(tmp_path: Path) -> Discovery:
    """A private run for tests that mutate cards or runtime state."""
    application = make_app(tmp_path)
    run = start_discovery(application.discovery_deps(), hk_request(), force_new=True)
    return Discovery(application, run, tmp_path)
