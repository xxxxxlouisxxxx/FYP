"""Access checks for a hosted dashboard.

``HOP_APP_PASSWORD`` locks the whole UI. ``HOP_REVIEW_PASSCODE`` keeps high-privilege roles
(including approval of HIGH cards) behind a second secret. Neither value is stored in the repo:
set them as environment variables, or as Streamlit Community Cloud secrets (Cloud exposes
top-level secrets as environment variables).
"""

from __future__ import annotations

import hmac
import os
import shutil
from pathlib import Path

from hop.bootstrap import App

LIMITED_ROLES = ("viewer", "analyst")


def app_password() -> str:
    return os.environ.get("HOP_APP_PASSWORD", "").strip()


def review_passcode() -> str:
    return os.environ.get("HOP_REVIEW_PASSCODE", "").strip()


def secret_matches(given: str, expected: str) -> bool:
    if not expected:
        return False
    return hmac.compare_digest(given.encode(), expected.encode())


def roles_for(*, all_roles: list[str], review_unlocked: bool) -> list[str]:
    """Roles the sidebar may offer. With no review passcode configured, every role is available."""
    if not review_passcode() or review_unlocked:
        return list(all_roles)
    return [role for role in all_roles if role in LIMITED_ROLES]


def seed_sandbox_markets(app: App, markets: tuple[str, ...] = ("HK", "SG", "US")) -> list[str]:
    """Run sandbox discovery for markets that have no successful run yet.

    Does nothing when a real provider or model is configured, so a hosted app cannot spend money
    by restarting. Returns the ids of runs started on this call.
    """
    from hop.platform.common_contracts import CollectionRequest, RunStatus
    from hop.products.opportunity_intelligence.pipeline import start_discovery

    settings = app.settings
    if settings.dataforseo_configured or settings.openai_configured:
        return []
    if settings.serp_provider not in ("auto", "sandbox") or settings.model_provider not in ("auto", "mock"):
        return []
    available = set(app.pack.markets)
    done = {
        run.request.get("market") for run in app.platform.runtime.list_runs(200) if run.status == RunStatus.SUCCEEDED
    }
    deps = app.discovery_deps("sandbox")
    started: list[str] = []
    for market in markets:
        if market not in available or market in done:
            continue
        request = CollectionRequest(
            domain_pack=app.pack.pack_id,
            market=market,
            tier="A",
            serp_provider="sandbox",
            model_provider="mock",
            requested_by="dashboard-seed",
            decision_question="Sandbox seed for the hosted dashboard",
        )
        started.append(start_discovery(deps, request).run_id)
    return started


def reset_sqlite_store(app: App) -> None:
    """Delete the file-backed SQLite database and local object store. The caller clears caches."""
    url = app.settings.database_url
    if not url.startswith("sqlite:///") or url.endswith(":memory:"):
        raise RuntimeError("reset is only supported for a file-backed SQLite database")
    app.platform.store.engine.dispose()
    path = Path(url.removeprefix("sqlite:///"))
    for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        candidate.unlink(missing_ok=True)
    objects = app.settings.object_store_dir
    if objects.exists():
        shutil.rmtree(objects)
