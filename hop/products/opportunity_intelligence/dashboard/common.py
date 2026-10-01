"""Shared dashboard helpers. Every rate is rendered with n and its Wilson CI; missing is shown as missing."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from hop.bootstrap import App, build_app
from hop.platform.common_contracts import MeasuredValue, Proportion, RunStatus
from hop.products.opportunity_intelligence.metrics import METRIC_DEFINITIONS, load_metrics

ROLES = ["viewer", "analyst", "domain_reviewer", "review_board", "platform_engineer", "admin"]
PRIORITY_COLOR = {"HIGH": "#c0392b", "MEDIUM": "#d68910", "LOW": "#7f8c8d"}
STATUS_ICON = {"DRAFT": "📝", "IN_REVIEW": "🔎", "APPROVED": "✅", "WATCHLIST": "👀", "REJECTED": "⛔"}


@st.cache_resource(show_spinner="Loading platform services…")
def get_app() -> App:
    return build_app()


def fmt_metric(m: MeasuredValue | Proportion | None, pct: bool = True, fmt: str = "{:,.2f}") -> str:
    if m is None:
        return "missing (NOT_COLLECTED)"
    if not m.is_observed:
        return f"missing ({m.state.value})"
    if isinstance(m, Proportion):
        rate = f"{m.rate:.0%}" if pct else f"{m.rate:.2f}"
        tag = " ⚠exploratory" if m.exploratory else ""
        return f"{rate} (n={m.n}, CI {m.ci_low:.0%}–{m.ci_high:.0%}){tag}"
    text = fmt.format(m.value)
    return f"{text} (n={m.n})" if m.n is not None else text


def rate_cols(prefix: str, m: MeasuredValue | Proportion | None) -> dict[str, Any]:
    """Split a proportion into rate / n / CI columns (None where missing, never 0)."""
    if isinstance(m, Proportion) and m.is_observed:
        return {f"{prefix}": round(m.rate or 0, 4), f"{prefix} n": m.n, f"{prefix} CI low": m.ci_low,
                f"{prefix} CI high": m.ci_high}  # fmt: skip
    state = m.state.value if m is not None else "NOT_COLLECTED"
    return {f"{prefix}": None, f"{prefix} n": None, f"{prefix} CI low": None, f"{prefix} CI high": None,
            f"{prefix} state": state}  # fmt: skip


def successful_runs(app: App) -> list[Any]:
    return [r for r in app.platform.runtime.list_runs(200) if r.status == RunStatus.SUCCEEDED]


def selected_run(app: App) -> Any | None:
    run_id = st.session_state.get("run_id")
    return app.platform.runtime.get(run_id) if run_id else None


def need_metrics(app: App, run_id: str) -> dict[str, dict[str, Any]]:
    return {r["need_id"]: load_metrics(r) for r in app.repo.metrics(run_id, "need")}


def brand_metrics(app: App, run_id: str) -> list[tuple[str, str, dict[str, Any]]]:
    return [(r["need_id"], r["brand_id"], load_metrics(r)) for r in app.repo.metrics(run_id, "brand")]


def need_label(app: App, need_id: str) -> str:
    need = app.pack.needs.get(need_id)
    return need.label.get("en", need_id) if need else need_id


def require_run(app: App) -> Any:
    run = selected_run(app)
    if run is None:
        st.info("No successful run selected. Start one with `hop collection run --market HK --tier A`, "
                "then pick it in the sidebar.")  # fmt: skip
        st.stop()
    return run


def metric_help(name: str) -> str:
    return METRIC_DEFINITIONS.get(name, name)


def sandbox_banner(app: App, run: Any | None) -> None:
    if (
        run is not None
        and run.request.get("serp_provider", "auto") in ("auto", "sandbox")
        and not app.settings.dataforseo_configured
    ):
        st.caption("🧪 Sandbox data: recorded provider fixtures and a deterministic mock model; costs are simulated.")


def df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def principal() -> tuple[str, str]:
    return st.session_state.get("user", "Demo Analyst"), st.session_state.get("role", "analyst")
