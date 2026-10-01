from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from hop.products.opportunity_intelligence.contracts import OpportunityStatus
from hop.products.opportunity_intelligence.dashboard.pages import PAGES
from tests.conftest import REPO_ROOT, Discovery, point_env_at

APP_FILE = REPO_ROOT / "hop" / "products" / "opportunity_intelligence" / "dashboard" / "app.py"


def page_script(page_name: str, role: str, user: str) -> None:
    import streamlit as st

    from hop.products.opportunity_intelligence.dashboard import pages
    from hop.products.opportunity_intelligence.dashboard.common import get_app, successful_runs

    st.session_state.setdefault("user", user)
    st.session_state.setdefault("role", role)
    st.session_state.setdefault("run_id", successful_runs(get_app())[0].run_id)
    getattr(pages, page_name)()


def _point_dashboard_at(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    point_env_at(data_dir, monkeypatch)
    st.cache_resource.clear()


@pytest.fixture
def shared(discovery: Discovery, monkeypatch: pytest.MonkeyPatch) -> Iterator[Discovery]:
    _point_dashboard_at(discovery.data_dir, monkeypatch)
    yield discovery
    st.cache_resource.clear()


def test_entry_point_renders_sidebar_and_navigation(shared: Discovery) -> None:
    at = AppTest.from_file(str(APP_FILE), default_timeout=60).run()
    assert not at.exception, [e.message for e in at.exception]
    assert {"Role (Entra ID placeholder)", "Run"} <= {s.label for s in at.sidebar.selectbox}


@pytest.mark.parametrize("role", ["viewer", "analyst", "review_board"])
@pytest.mark.parametrize("page", [fn.__name__ for fn, _title, _icon in PAGES])
def test_every_page_renders_for_every_role(shared: Discovery, page: str, role: str) -> None:
    at = AppTest.from_function(page_script, args=(page, role, "Demo User"), default_timeout=60).run()
    assert not at.exception, [e.message for e in at.exception]


def test_seven_spec_pages() -> None:
    assert len(PAGES) == 7


def test_missing_values_are_displayed_as_missing(shared: Discovery) -> None:
    at = AppTest.from_function(
        page_script, args=("consumer_need_explorer", "analyst", "Demo"), default_timeout=60
    ).run()
    rendered = " ".join(str(df.value.to_dict()) for df in at.dataframe)
    assert "missing" in rendered.lower()


def test_approve_from_evidence_room(fresh_discovery: Discovery, monkeypatch: pytest.MonkeyPatch) -> None:
    _point_dashboard_at(fresh_discovery.data_dir, monkeypatch)
    at = AppTest.from_function(page_script, args=("evidence_room", "review_board", "Ada Chan"), default_timeout=60)
    at.run()
    card_id = at.selectbox[0].value
    next(t for t in at.text_input if t.label.startswith("Accountable owner")).input("Sourcing Desk HK")
    next(b for b in at.button if "Approve" in b.label).click().run()
    assert not at.exception, [e.message for e in at.exception]
    assert any("APPROVED" in s.value for s in at.success)
    card = fresh_discovery.app.repo.card(card_id)
    assert card.status == OpportunityStatus.APPROVED and card.approver == "Ada Chan"
    st.cache_resource.clear()
