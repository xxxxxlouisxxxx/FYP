from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from hop.bootstrap import App, build_app
from hop.platform.common_contracts import CollectionRequest, CollectionRun
from hop.platform.settings import Settings
from hop.products.opportunity_intelligence.pipeline import start_discovery

REPO_ROOT = Path(__file__).resolve().parents[1]

# Set to a Postgres URL whose role has CREATEDB (e.g. postgresql+psycopg://hop:hop@localhost:5432/postgres)
# to run the whole suite against Postgres; each test data dir gets its own throwaway database.
POSTGRES_ADMIN_URL = os.environ.get("HOP_TEST_DATABASE_URL") or None
_created_databases: set[str] = set()


def database_url_for(data_dir: Path) -> str:
    if POSTGRES_ADMIN_URL is None:
        return f"sqlite:///{data_dir / 'hop.db'}"
    name = "hoptest_" + hashlib.sha256(str(data_dir.resolve()).encode()).hexdigest()[:16]
    admin = make_url(POSTGRES_ADMIN_URL)
    if name not in _created_databases:
        engine = create_engine(admin, isolation_level="AUTOCOMMIT")
        with engine.connect() as conn:
            if conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}).first() is None:
                conn.execute(text(f'CREATE DATABASE "{name}"'))
        engine.dispose()
        _created_databases.add(name)
    return admin.set(database=name).render_as_string(hide_password=False)


def point_env_at(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure env-driven entry points (CLI, dashboard) to use ``data_dir`` and its test database."""
    monkeypatch.setenv("HOP_DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", database_url_for(data_dir))
    monkeypatch.setenv("HOP_SERP_PROVIDER", "sandbox")
    monkeypatch.setenv("HOP_MODEL_PROVIDER", "mock")
    monkeypatch.setenv("HOP_DOMAIN_PACKS_DIR", str(REPO_ROOT / "domain_packs"))


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if POSTGRES_ADMIN_URL is not None:
        return
    skip = pytest.mark.skip(reason="set HOP_TEST_DATABASE_URL to run Postgres-only tests")
    for item in items:
        if "postgres" in item.keywords:
            item.add_marker(skip)


def _drop_databases(names: set[str]) -> None:
    if POSTGRES_ADMIN_URL is None or not names:
        return
    engine = create_engine(make_url(POSTGRES_ADMIN_URL), isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        for name in sorted(names):
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    engine.dispose()
    _created_databases.difference_update(names)


@pytest.fixture(scope="session", autouse=True)
def _drop_session_databases() -> Iterator[None]:
    yield
    _drop_databases(set(_created_databases))


@pytest.fixture(autouse=True)
def _drop_test_databases() -> Iterator[None]:
    """Databases created by a test are dropped right after it; session fixtures' databases already exist."""
    before = set(_created_databases)
    yield
    _drop_databases(_created_databases - before)


def make_settings(data_dir: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "data_dir": data_dir,
        "database_url": database_url_for(data_dir),
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
