from __future__ import annotations

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from hop.bootstrap import build_app
from hop.products.opportunity_intelligence.dashboard.access import (
    reset_sqlite_store,
    roles_for,
    secret_matches,
    seed_sandbox_markets,
)
from hop.products.opportunity_intelligence.dashboard.common import ROLES, successful_runs
from tests.conftest import REPO_ROOT, point_env_at

APP_FILE = REPO_ROOT / "hop" / "products" / "opportunity_intelligence" / "dashboard" / "app.py"


def test_secret_matches_rejects_empty_and_wrong() -> None:
    assert secret_matches("anything", "") is False
    assert secret_matches("nope", "secret") is False
    assert secret_matches("secret", "secret") is True


def test_review_roles_stay_limited_until_unlocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOP_REVIEW_PASSCODE", "review-secret")
    assert roles_for(all_roles=ROLES, review_unlocked=False) == ["viewer", "analyst"]
    assert "review_board" in roles_for(all_roles=ROLES, review_unlocked=True)
    monkeypatch.delenv("HOP_REVIEW_PASSCODE")
    assert roles_for(all_roles=ROLES, review_unlocked=False) == ROLES


def test_seed_is_idempotent_and_skipped_for_live_providers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    point_env_at(tmp_path, monkeypatch)
    app = build_app()
    started = seed_sandbox_markets(app)
    assert len(started) == 3
    assert {run.request["market"] for run in successful_runs(app)} == {"HK", "SG", "US"}
    assert seed_sandbox_markets(app) == []
    assert len(successful_runs(app)) == 3

    monkeypatch.setenv("DATAFORSEO_LOGIN", "login")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "password")
    live = build_app()
    assert live.settings.dataforseo_configured
    assert seed_sandbox_markets(live) == []


def test_reset_sqlite_store_allows_a_fresh_seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    point_env_at(tmp_path, monkeypatch)
    app = build_app()
    seed_sandbox_markets(app)
    reset_sqlite_store(app)
    fresh = build_app()
    assert successful_runs(fresh) == []
    assert len(seed_sandbox_markets(fresh)) == 3


def test_password_gate_shows_nothing_until_the_password_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    point_env_at(tmp_path, monkeypatch)
    monkeypatch.setenv("HOP_APP_PASSWORD", "open-sesame")
    monkeypatch.setenv("HOP_REVIEW_PASSCODE", "review-secret")
    st.cache_resource.clear()

    locked = AppTest.from_file(str(APP_FILE), default_timeout=30).run()
    assert not locked.exception, [e.message for e in locked.exception]
    assert any(box.label == "Password" for box in locked.text_input)
    assert not any(box.label == "Role (Entra ID placeholder)" for box in locked.sidebar.selectbox)
    assert successful_runs(build_app()) == []

    locked.text_input[0].input("wrong")
    locked.button[0].click().run()
    assert any("Wrong password" in item.value for item in locked.error)
    assert successful_runs(build_app()) == []

    locked.text_input[0].input("open-sesame")
    locked.button[0].click().run(timeout=180)
    assert not locked.exception, [e.message for e in locked.exception]
    role = next(box for box in locked.sidebar.selectbox if box.label == "Role (Entra ID placeholder)")
    assert list(role.options) == ["viewer", "analyst"]
    assert {run.request["market"] for run in successful_runs(build_app())} == {"HK", "SG", "US"}
    st.cache_resource.clear()
