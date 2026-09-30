"""Streamlit entry point: ``streamlit run hop/products/opportunity_intelligence/dashboard/app.py``."""

from __future__ import annotations

import streamlit as st

from hop.products.opportunity_intelligence.dashboard.common import ROLES, get_app, successful_runs
from hop.products.opportunity_intelligence.dashboard.pages import PAGES

st.set_page_config(page_title="HKTDC Hidden Opportunity Discovery", page_icon="👟", layout="wide")


def sidebar() -> None:
    app = get_app()
    st.sidebar.markdown("### 👟 Hidden Opportunity Discovery")
    st.sidebar.caption(f"Domain pack **{app.pack.pack_id}** v{app.pack.version}")
    st.sidebar.text_input("Your name (reviewer identity)", value="Demo Analyst", key="user")
    st.sidebar.selectbox("Role (Entra ID placeholder)", ROLES, index=ROLES.index("analyst"), key="role")
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


sidebar()
navigation = st.navigation([st.Page(fn, title=title, icon=icon, url_path=fn.__name__) for fn, title, icon in PAGES])
navigation.run()
