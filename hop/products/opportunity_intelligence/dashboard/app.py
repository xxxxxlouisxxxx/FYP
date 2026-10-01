"""Streamlit entry point: ``streamlit run hop/products/opportunity_intelligence/dashboard/app.py``."""

from __future__ import annotations

import streamlit as st

from hop.products.opportunity_intelligence.dashboard.access import (
    app_password,
    review_passcode,
    roles_for,
    secret_matches,
)
from hop.products.opportunity_intelligence.dashboard.common import ROLES, ensure_demo_data, get_app, successful_runs
from hop.products.opportunity_intelligence.dashboard.pages import PAGES

st.set_page_config(page_title="HKTDC Hidden Opportunity Discovery", page_icon="👟", layout="wide")


def unlock_gate() -> bool:
    """Show only a password form until ``HOP_APP_PASSWORD`` matches. No app services are loaded before that."""
    expected = app_password()
    if not expected or st.session_state.get("app_unlocked"):
        return True
    st.title("Hidden Opportunity Discovery")
    st.info("This dashboard is private. Enter the access password to continue. Sandbox figures are simulated.")
    with st.form("unlock"):
        given = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Open")
    if submitted:
        if secret_matches(given, expected):
            st.session_state["app_unlocked"] = True
            st.rerun()
        else:
            st.error("Wrong password.")
    return False


def sidebar() -> None:
    app = get_app()
    st.sidebar.markdown("### 👟 Hidden Opportunity Discovery")
    st.sidebar.caption(f"Domain pack **{app.pack.pack_id}** v{app.pack.version}")
    st.sidebar.text_input("Your name (reviewer identity)", value="Demo Analyst", key="user")
    if review_passcode() and not st.session_state.get("review_unlocked"):
        with st.sidebar.form("review_unlock"):
            given = st.text_input("Review passcode", type="password")
            if st.form_submit_button("Unlock review"):
                if secret_matches(given, review_passcode()):
                    st.session_state["review_unlocked"] = True
                    st.rerun()
                else:
                    st.error("Wrong review passcode.")
    roles = roles_for(all_roles=ROLES, review_unlocked=bool(st.session_state.get("review_unlocked")))
    if st.session_state.get("role") not in roles:
        st.session_state["role"] = "analyst" if "analyst" in roles else roles[0]
    st.sidebar.selectbox("Role (Entra ID placeholder)", roles, key="role")
    runs = successful_runs(app)
    markets = sorted({r.request["market"] for r in runs})
    st.sidebar.selectbox("Market filter", ["All", *markets], key="market_filter")
    market = st.session_state.get("market_filter")
    scoped = [r for r in runs if market in (None, "All") or r.request["market"] == market]
    if scoped:
        labels = {r.run_id: f"{r.request['market']} tier {r.request['tier']} · {r.created_at:%m-%d %H:%M} · {r.run_id[-6:]}"
                  for r in scoped}  # fmt: skip
        st.sidebar.selectbox("Run", list(labels), format_func=labels.get, key="run_id")
    else:
        st.session_state["run_id"] = None
        st.sidebar.info("No successful runs yet.")
    st.sidebar.caption(
        f"DB: `{app.settings.database_url.split('://')[0]}` · model: `{app.platform.gateway.default_model}`"
    )


if not unlock_gate():
    st.stop()

if app_password():
    st.info("Private sandbox. Figures come from recorded fixtures and a mock model, not live providers.")

ensure_demo_data()
sidebar()
navigation = st.navigation([st.Page(fn, title=title, icon=icon, url_path=fn.__name__) for fn, title, icon in PAGES])
navigation.run()
