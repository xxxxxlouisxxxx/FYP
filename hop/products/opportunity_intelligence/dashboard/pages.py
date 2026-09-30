"""The seven dashboard pages of spec section 14."""

from __future__ import annotations

import json
from collections import Counter

import altair as alt
import pandas as pd
import streamlit as st

from hop.platform.common_contracts import ReviewAction
from hop.platform.observability import span_tree
from hop.platform.policy_engine import PolicyViolation
from hop.products.opportunity_intelligence.contracts import OpportunityStatus
from hop.products.opportunity_intelligence.dashboard.common import (
    PRIORITY_COLOR,
    STATUS_ICON,
    brand_metrics,
    df,
    fmt_metric,
    get_app,
    need_label,
    need_metrics,
    principal,
    rate_cols,
    require_run,
    sandbox_banner,
    selected_run,
)
from hop.products.opportunity_intelligence.opportunity_lifecycle import LifecycleError

PRIORITY_SCALE = alt.Scale(domain=list(PRIORITY_COLOR), range=list(PRIORITY_COLOR.values()))


# 1. Executive Portfolio ------------------------------------------------------------------------
def executive_portfolio() -> None:
    app = get_app()
    st.title("Executive Portfolio")
    st.caption("Governed Opportunity Cards across runs. Nothing here is approved without a named human reviewer.")
    market = st.session_state.get("market_filter")
    cards = app.repo.cards(market=None if market in (None, "All") else market)
    sandbox_banner(app, selected_run(app))
    status_counts = Counter(c.status.value for c in cards)
    cols = st.columns(6)
    cols[0].metric("Opportunity Cards", len(cards))
    for i, s in enumerate(["DRAFT", "IN_REVIEW", "APPROVED", "WATCHLIST", "REJECTED"], 1):
        cols[i].metric(f"{STATUS_ICON[s]} {s.replace('_', ' ').title()}", status_counts.get(s, 0))
    if not cards:
        st.info("No cards yet. Run `hop collection run --market HK --tier A`.")
        return
    runs = app.platform.runtime.list_runs(200)
    c1, c2, c3 = st.columns(3)
    c1.metric("High-priority cards", sum(c.priority == "HIGH" for c in cards))
    c2.metric("Runs (all statuses)", len(runs))
    c3.metric("Spend recorded (simulated in sandbox)", f"${sum(r.actual_cost_usd for r in runs):.4f}")
    rows = [{
        "card": c.card_id, "status": f"{STATUS_ICON[c.status.value]} {c.status.value}", "priority": c.priority,
        "score": c.score.total, "confidence": c.confidence_label, "market": c.market, "title": c.title,
        "gap family": c.gap_family, "evidence +": len(c.supporting_evidence_ids), "counter": len(c.counter_evidence_ids),
        "owner": c.owner or "", "run": c.run_id,
    } for c in cards]  # fmt: skip
    frame = df(rows)
    left, right = st.columns([3, 2])
    with left:
        st.subheader("Portfolio (ranked by deterministic score)")
        st.dataframe(
            frame,
            hide_index=True,
            width="stretch",
            column_config={"score": st.column_config.ProgressColumn("score", min_value=0, max_value=1, format="%.3f")},
        )
    with right:
        st.subheader("Score vs evidence confidence")
        scatter = pd.DataFrame(
            [
                {
                    "score": c.score.total,
                    "evidence confidence": c.evidence_confidence,
                    "priority": c.priority,
                    "title": c.title,
                    "status": c.status.value,
                }
                for c in cards
            ]
        )
        st.altair_chart(
            alt.Chart(scatter).mark_circle(size=140, opacity=0.8).encode(
                x=alt.X("evidence confidence:Q", scale=alt.Scale(domain=[0, 1])),
                y=alt.Y("score:Q", scale=alt.Scale(domain=[0, 1])),
                color=alt.Color("priority:N", scale=PRIORITY_SCALE), tooltip=["title", "score", "status"],
            ).properties(height=260), width="stretch")  # fmt: skip
        fam = pd.DataFrame(Counter(c.gap_family for c in cards).items(), columns=["gap family", "cards"])
        st.altair_chart(alt.Chart(fam).mark_bar().encode(x="cards:Q", y=alt.Y("gap family:N", sort="-x"))
                        .properties(height=200), width="stretch")  # fmt: skip
    st.caption("Scores are rule-based (score-v1.0.0 weights 0.30/0.20/0.20/0.15/0.10/0.05 minus risk penalties) and "
               "must be calibrated with HKTDC stakeholders before being used for decisions.")  # fmt: skip


# 2. Consumer Need Explorer ---------------------------------------------------------------------
def consumer_need_explorer() -> None:
    app = get_app()
    run = require_run(app)
    st.title("Consumer Need Explorer")
    st.caption(f"Run {run.run_id} · market {run.request['market']} · tier {run.request['tier']}")
    sandbox_banner(app, run)
    metrics = need_metrics(app, run.run_id)
    rows = []
    for need_id, m in sorted(metrics.items(), key=lambda kv: -(kv[1]["demand.index"].value or -1)):
        need = app.pack.needs[need_id]
        vol, idx, trend, cov = m["demand.search_volume"], m["demand.index"], m["demand.trend_yoy"], m["demand.coverage"]
        rows.append({
            "need": need.label.get("en", need_id), "中文": need.label.get("zh-Hant", ""), "parent": need.parent or "",
            "monthly searches": fmt_metric(vol, fmt="{:,.0f}"), "demand index": fmt_metric(idx),
            "trend YoY": "missing (" + trend.state.value + ")" if not trend.is_observed else f"{trend.value:+.0%} (n={trend.n})",
            "coverage": fmt_metric(cov), "strategic relevance": need.strategic_relevance,
            "feasibility": need.feasibility, "regulatory": ", ".join(need.regulatory_flags) or "-",
        })  # fmt: skip
    st.dataframe(df(rows), hide_index=True, width="stretch")
    chart_rows = [{"need": need_label(app, n), "demand index": m["demand.index"].value} for n, m in metrics.items()
                  if m["demand.index"].is_observed]  # fmt: skip
    if chart_rows:
        st.altair_chart(alt.Chart(pd.DataFrame(chart_rows)).mark_bar().encode(
            x=alt.X("demand index:Q", scale=alt.Scale(domain=[0, 1])), y=alt.Y("need:N", sort="-x"))
            .properties(height=260), width="stretch")  # fmt: skip
    missing = [need_label(app, n) for n, m in metrics.items() if not m["demand.index"].is_observed]
    if missing:
        st.warning("Demand missing (not zero) for: " + ", ".join(missing))
    need_id = st.selectbox("Inspect need", sorted(metrics), format_func=lambda n: need_label(app, n))
    need = app.pack.needs[need_id]
    st.markdown(f"**{need.label.get('en')}** / {need.label.get('zh-Hant', '')} — {need.description}")
    st.markdown(f"Attributes: `{', '.join(need.attributes)}` · On-need match terms: `{', '.join(need.match_terms)}`")
    obs = [o for o in app.repo.observations(run.run_id, "demand") if o.need_id == need_id]
    st.dataframe(df([{"query": o.query_text, "language": o.language, "status": o.status.value,
                      "volume": o.payload.get("search_volume"), "trend": o.payload.get("trend_yoy"),
                      "retries": o.retry_count, "error": o.error or ""} for o in obs]), hide_index=True,
                 width="stretch")  # fmt: skip


# 3. SERP Landscape -----------------------------------------------------------------------------
def serp_landscape() -> None:
    app = get_app()
    run = require_run(app)
    st.title("SERP Landscape")
    st.caption("Top-10 organic Google results per need query. Supply = on-need product page from a manufacturer, "
               "retailer or marketplace.")  # fmt: skip
    sandbox_banner(app, run)
    metrics = need_metrics(app, run.run_id)
    rows = [{"need": need_label(app, n), "supply share": fmt_metric(m["serp.supply_share"]),
             "top-3 supply": fmt_metric(m["serp.top3_supply_share"]), "domain diversity": fmt_metric(m["serp.domain_diversity"]),
             "shopping feature": fmt_metric(m["serp.shopping_feature_rate"]), "PAA": fmt_metric(m["serp.paa_rate"]),
             "brand HHI": fmt_metric(m["serp.brand_hhi"]), "volatility": fmt_metric(m["serp.volatility"])}
            for n, m in sorted(metrics.items())]  # fmt: skip
    st.dataframe(df(rows), hide_index=True, width="stretch")
    ci = [{"need": need_label(app, n), **rate_cols("supply", m["serp.supply_share"])} for n, m in metrics.items()]
    ci_df = pd.DataFrame([r for r in ci if r.get("supply") is not None])
    if not ci_df.empty:
        base = alt.Chart(ci_df).encode(y=alt.Y("need:N", sort="x"))
        st.altair_chart((base.mark_rule(strokeWidth=3, opacity=0.5).encode(x=alt.X("supply CI low:Q", title="supply share (95% Wilson CI)", scale=alt.Scale(domain=[0, 1])), x2="supply CI high:Q")
                         + base.mark_point(filled=True, size=90).encode(x="supply:Q", tooltip=["need", "supply", "supply n"])).properties(height=280),
                        width="stretch")  # fmt: skip
    brand_rows = [{"need": need_label(app, n), "brand": app.resolver.name(b), "SERP brand share": fmt_metric(m.get("serp.brand_share"))}
                  for n, b, m in brand_metrics(app, run.run_id) if m.get("serp.brand_share") is not None and (m["serp.brand_share"].rate or 0) > 0]  # fmt: skip
    with st.expander(f"Brand visibility in SERP ({len(brand_rows)} need×brand pairs)"):
        st.dataframe(df(brand_rows), hide_index=True, width="stretch")
    serp_obs = app.repo.observations(run.run_id, "serp")
    q = st.selectbox(
        "Inspect query",
        [o.observation_id for o in serp_obs],
        format_func=lambda oid: next(f"{o.query_text} [{o.status.value}]" for o in serp_obs if o.observation_id == oid),
    )
    o = next(x for x in serp_obs if x.observation_id == q)
    if not o.payload.get("organic"):
        st.error(
            f"No SERP data: {o.status.value} — {o.error or 'not collected'}. Shown as missing, not as zero supply."
        )
        return
    st.dataframe(df([{"rank": r["rank"], "domain": r["domain"], "source type": r["source_type"], "on-need": r["on_need"],
                      "supply": r["supply"], "title": r["title"],
                      "⚠ injection": ", ".join(r["injection_findings"]) or ""} for r in o.payload["organic"]]),
                 hide_index=True, width="stretch")  # fmt: skip
    if "PROMPT_INJECTION_SUSPECTED" in o.quality_flags:
        st.warning("This SERP contains text that looks like prompt injection. Those results are quarantined and are "
                   "never used as supporting evidence.")  # fmt: skip


# 4. GERP Landscape -----------------------------------------------------------------------------
def gerp_landscape() -> None:
    app = get_app()
    run = require_run(app)
    st.title("GERP Landscape")
    st.caption("Generative-engine answers, repeated per query. Mentions, recommendations and exclusions are counted "
               "separately; a mention is never a recommendation.")  # fmt: skip
    sandbox_banner(app, run)
    metrics = need_metrics(app, run.run_id)
    rows = [{"need": need_label(app, n), "answers": fmt_metric(m["gerp.answers"], fmt="{:.0f}"),
             "recommendation coverage": fmt_metric(m["gerp.recommendation_coverage"]),
             "primary pick": fmt_metric(m["gerp.primary_rate"]), "mention only": fmt_metric(m["gerp.mention_only_rate"]),
             "exclusion": fmt_metric(m["gerp.exclusion_rate"]), "stability": fmt_metric(m["gerp.stability"]),
             "citation support": fmt_metric(m["gerp.citation_support"])} for n, m in sorted(metrics.items())]  # fmt: skip
    st.dataframe(df(rows), hide_index=True, width="stretch")
    brand_rows = []
    for n, b, m in brand_metrics(app, run.run_id):
        if "gerp.brand_recommendation_rate" not in m or not m["gerp.brand_recommendation_rate"].is_observed:
            continue
        brand_rows.append({"need": need_label(app, n), "brand": app.resolver.name(b),
                           "recommended": fmt_metric(m["gerp.brand_recommendation_rate"]),
                           "primary": fmt_metric(m["gerp.brand_primary_rate"]),
                           "mentioned only": fmt_metric(m["gerp.brand_mention_rate"]),
                           "excluded": fmt_metric(m["gerp.brand_exclusion_rate"])})  # fmt: skip
    st.subheader("Brand recommendation vs mention vs exclusion")
    st.dataframe(df(brand_rows), hide_index=True, width="stretch", height=280)
    gerp_obs = app.repo.observations(run.run_id, "gerp")
    oid = st.selectbox("Inspect answer", [o.observation_id for o in gerp_obs],
                       format_func=lambda i: next(f"{o.query_text} · repeat {o.repeat_index + 1}" + (" ⚠" if o.quality_flags else "")
                                                  for o in gerp_obs if o.observation_id == i))  # fmt: skip
    o = next(x for x in gerp_obs if x.observation_id == oid)
    text = o.payload.get("answer_text", "")
    mentions = sorted(
        (x for x in app.repo.mentions(run.run_id, "gerp") if x["observation_id"] == oid), key=lambda x: x["start"]
    )
    colors = {
        "PRIMARY_RECOMMENDATION": "#1e8449",
        "SUPPORTING_RECOMMENDATION": "#2874a6",
        "MENTION": "#7f8c8d",
        "EXCLUSION": "#c0392b",
    }
    html, pos = [], 0
    for x in mentions:
        html.append(_esc(text[pos : x["start"]]))
        tag = x["label"] if x["resolution"] == "RESOLVED" else f"AMBIGUOUS ({x['resolution']})"
        color = colors.get(x["label"], "#7f8c8d") if x["resolution"] == "RESOLVED" else "#b7950b"
        html.append(f"<span style='border-bottom:3px solid {color};font-weight:600' title='{tag}'>{_esc(text[x['start']:x['end']])}"
                    f"<sup style='color:{color}'>{tag.split('_')[0].lower()}</sup></span>")  # fmt: skip
        pos = x["end"]
    html.append(_esc(text[pos:]))
    st.markdown(f"<div style='padding:12px;border:1px solid #ddd;border-radius:8px;line-height:1.7'>{''.join(html)}</div>",
                unsafe_allow_html=True)  # fmt: skip
    st.caption(
        f"model {o.model_id} · prompt {o.prompt_id}@{o.prompt_version} · citations: {', '.join(o.payload.get('citations', [])) or 'none'}"
    )
    if o.quality_flags:
        st.warning(f"Quality flags: {o.quality_flags}. Suspected injected instructions were skipped by the extractor.")


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# 5. SERP-GERP Gap Matrix -----------------------------------------------------------------------
def gap_matrix() -> None:
    app = get_app()
    run = require_run(app)
    st.title("SERP–GERP Gap Matrix")
    st.caption("Deterministic gap-rule outcomes per need. UNKNOWN means an input metric is missing — it is never "
               "evaluated as zero.")  # fmt: skip
    sandbox_banner(app, run)
    matrix = app.platform.runtime.checkpoints(run.run_id).get("gap_detection", {}).get("matrix", [])
    need_rows = [e for e in matrix if e["brand_id"] is None]
    if need_rows:
        pivot = pd.DataFrame(need_rows).assign(need=lambda d: d["need_id"].map(lambda n: need_label(app, n)))
        st.altair_chart(alt.Chart(pivot).mark_rect(stroke="white").encode(
            x=alt.X("rule_id:N", title="gap rule"), y=alt.Y("need:N", title=None),
            color=alt.Color("outcome:N", scale=alt.Scale(domain=["MATCHED", "NOT_MATCHED", "UNKNOWN"],
                                                         range=["#c0392b", "#d5dbdb", "#f4d03f"])),
            tooltip=["need", "rule_id", "outcome"]).properties(height=320), width="stretch")  # fmt: skip
    metrics = need_metrics(app, run.run_id)
    pts = []
    for n, m in metrics.items():
        s, g, v = m["serp.supply_share"], m["gerp.recommendation_coverage"], m["demand.search_volume"]
        pts.append({"need": need_label(app, n), "SERP supply share": s.rate if s.is_observed else None,
                    "GERP recommendation coverage": g.rate if g.is_observed else None,
                    "monthly searches": v.value if v.is_observed else None,
                    "serp n": s.n, "gerp n": g.n})  # fmt: skip
    pts_df = pd.DataFrame(pts)
    plot = pts_df.dropna(subset=["SERP supply share", "GERP recommendation coverage"])
    st.subheader("Supply vs recommendation (bubble = demand)")
    st.altair_chart(alt.Chart(plot).mark_circle(opacity=0.7).encode(
        x=alt.X("SERP supply share:Q", scale=alt.Scale(domain=[0, 1])),
        y=alt.Y("GERP recommendation coverage:Q", scale=alt.Scale(domain=[0, 1])),
        size=alt.Size("monthly searches:Q", legend=None), tooltip=["need", "SERP supply share", "serp n",
                                                                    "GERP recommendation coverage", "gerp n", "monthly searches"],
    ).properties(height=320), width="stretch")  # fmt: skip
    dropped = pts_df[pts_df[["SERP supply share", "GERP recommendation coverage"]].isna().any(axis=1)]
    if not dropped.empty:
        st.warning("Not plotted because a signal is missing: " + ", ".join(dropped["need"]))
    user, role = principal()
    st.subheader("What-if thresholds (not persisted)")
    allowed = app.platform.policy.check_permission(user, role, "gap_matrix:tune").allowed
    if not allowed:
        st.info(f"Role `{role}` cannot tune gap thresholds (needs gap_matrix:tune).")
        return
    c1, c2, c3 = st.columns(3)
    d_min = c1.slider("min demand index", 0.0, 1.0, 0.55, 0.05)
    s_max = c2.slider("max SERP supply share", 0.0, 1.0, 0.40, 0.05)
    g_max = c3.slider("max GERP recommendation coverage", 0.0, 1.0, 0.50, 0.05)
    what_if = []
    for n, m in metrics.items():
        d, s, g = m["demand.index"], m["serp.supply_share"], m["gerp.recommendation_coverage"]

        def cmp(val: float | None, ok: bool) -> str:
            return "UNKNOWN" if val is None else ("✔" if ok else "✘")

        what_if.append({"need": need_label(app, n),
                        "demand ≥": cmp(d.value if d.is_observed else None, (d.value or 0) >= d_min),
                        "SERP supply ≤": cmp(s.rate if s.is_observed else None, (s.rate or 0) <= s_max),
                        "GERP coverage ≤": cmp(g.rate if g.is_observed else None, (g.rate or 0) <= g_max)})  # fmt: skip
    st.dataframe(df(what_if), hide_index=True, width="stretch")
    st.caption("Changing production thresholds requires a new rule-set version, rule tests and approval.")


# 6. Opportunity Evidence Room ------------------------------------------------------------------
def evidence_room() -> None:
    app = get_app()
    st.title("Opportunity Evidence Room")
    cards = app.repo.cards()
    if not cards:
        st.info("No Opportunity Cards yet.")
        return
    default = st.session_state.get("card_id")
    ids = [c.card_id for c in cards]
    card_id = st.selectbox("Opportunity Card", ids, index=ids.index(default) if default in ids else 0,
                           format_func=lambda i: next(f"{STATUS_ICON[c.status.value]} [{c.priority}] {c.score.total:.3f} · {c.title}"
                                                      for c in cards if c.card_id == i))  # fmt: skip
    st.session_state["card_id"] = card_id
    card = app.repo.card(card_id)
    assert card is not None
    flash = st.session_state.pop("flash", None)
    if flash:
        (st.success if flash[0] == "ok" else st.error)(flash[1])
    st.subheader(card.title)
    c = st.columns(5)
    c[0].metric("Status", f"{STATUS_ICON[card.status.value]} {card.status.value}")
    c[1].metric("Priority", card.priority)
    c[2].metric("Score", f"{card.score.total:.3f}")
    c[3].metric("Confidence", card.confidence_label)
    c[4].metric("Lineage", "verified" if card.lineage_verified else "BROKEN")
    st.info(card.explanation.summary)
    st.caption(f"Explanation: {card.explanation.generator}" + (f" ({card.explanation.model_id}, {card.explanation.prompt_id}@"
               f"{card.explanation.prompt_version})" if card.explanation.model_id else "") + f" · validated={card.explanation.validated}"
               + (f" · {'; '.join(card.explanation.validation_notes)}" if card.explanation.validation_notes else ""))  # fmt: skip
    tabs = st.tabs(
        ["Findings", "Score", "Admission gates", "Supporting evidence", "Counter-evidence", "Review & audit"]
    )
    with tabs[0]:
        for title, group, icon in (("Observed", card.observed, "🔍"), ("Inferred", card.inferred, "💡"),
                                   ("Unknown", card.unknowns, "❓"), ("Limitations", card.limitations, "⚠️")):  # fmt: skip
            st.markdown(f"**{icon} {title}**")
            if not group:
                st.markdown("- none")
            for s in group:
                st.markdown(f"- {s.text} " + (f"`{len(s.evidence_ids)} evidence`" if s.evidence_ids else ""))
        st.markdown(f"**Next validation action:** {card.next_validation_action}")
        st.markdown("**Sample sizes:** " + "; ".join(f"`{k}` {fmt_metric(v)}" for k, v in card.sample_summary.items()))
    with tabs[1]:
        comp = pd.DataFrame([{"component": x.component_id, "weight": x.weight,
                              "value": x.value if x.value is not None else float("nan"), "contribution": x.contribution,
                              "source": x.source, "rationale": x.rationale} for x in card.score.components])  # fmt: skip
        st.dataframe(comp, hide_index=True, width="stretch")
        pens = list(card.score.penalties)
        st.dataframe(df([{"penalty": p.label, "applied": p.applied, "amount": p.amount, "reason": p.reason} for p in pens]),
                     hide_index=True, width="stretch")  # fmt: skip
        st.markdown(f"`{card.score.formula}` → gross **{card.score.gross:.3f}** − penalties **{card.score.total_penalty:.3f}** "
                    f"= **{card.score.total:.3f}** ({card.score.score_version}; rule {card.rule_id}@{card.rule_version})")  # fmt: skip
    candidate = next((x for x in app.repo.candidates(card.run_id) if x.candidate_id == card.candidate_id), None)
    with tabs[2]:
        if candidate:
            st.dataframe(df([{"gate": g.label, "passed": "✅" if g.passed else "❌", "severity": g.severity, "detail": g.detail}
                             for g in candidate.gate_results]), hide_index=True, width="stretch")  # fmt: skip
    ev = app.platform.evidence
    cache: dict[str, str] = {}

    def evidence_table(ids: list[str]) -> pd.DataFrame:
        rows = []
        for i in ids:
            e = ev.get(i)
            if e is None:
                rows.append({"evidence": i, "claim": "NOT FOUND"})
                continue
            lin = ev.verify_lineage(i, cache)
            rows.append({"type": e.evidence_type.value, "claim": e.extracted_claim, "source": e.source_provider,
                         "observed": e.observed_at.strftime("%Y-%m-%d %H:%M"), "lineage": "✅" if lin.valid else f"❌ {lin.reason}",
                         "sha256": e.content_hash[:12] + "…", "quality": e.data_quality_status.value, "evidence": e.evidence_id})  # fmt: skip
        return pd.DataFrame(rows)

    with tabs[3]:
        st.dataframe(evidence_table(card.supporting_evidence_ids), hide_index=True, width="stretch")
        st.caption("Evidence text is untrusted third-party content: displayed as data, never executed as instructions.")
    with tabs[4]:
        st.markdown(f"Status: **{card.counter_evidence_status.value}**")
        if candidate:
            for note in candidate.counter_evidence_notes:
                st.markdown(f"- {note}")
        if card.counter_evidence_ids:
            st.dataframe(evidence_table(card.counter_evidence_ids), hide_index=True, width="stretch")
    with tabs[5]:
        reviews = app.repo.reviews(card.card_id)
        st.dataframe(df([{"when": d.decided_at.strftime("%Y-%m-%d %H:%M:%S"), "reviewer": d.reviewer, "role": d.reviewer_role,
                          "action": d.action.value, "from": d.from_status, "to": d.to_status, "owner": d.owner_assigned or "",
                          "rationale": d.rationale or ""} for d in reviews]), hide_index=True, width="stretch")  # fmt: skip
        audit = app.platform.audit.list(resource_id=card.card_id, limit=50)
        st.dataframe(df([{"when": a.occurred_at.strftime("%Y-%m-%d %H:%M:%S"), "actor": a.actor, "action": a.action,
                          "outcome": a.outcome, "hash": (a.event_hash or "")[:12]} for a in audit]),
                     hide_index=True, width="stretch")  # fmt: skip
    _review_panel(card)


def _review_panel(card: object) -> None:
    app = get_app()
    user, role = principal()
    st.divider()
    st.subheader("Human review")
    allowed = [a for a in app.lifecycle.allowed_actions(card) if a != ReviewAction.SUBMIT_FOR_REVIEW]  # type: ignore[arg-type]
    if card.status == OpportunityStatus.DRAFT:  # type: ignore[attr-defined]
        allowed = [ReviewAction.APPROVE, ReviewAction.WATCHLIST, ReviewAction.REJECT]
    st.caption(f"Acting as **{user}** (role `{role}`). Required approver role: `{card.required_approver_role}`. "  # type: ignore[attr-defined]
               "Draft cards are submitted for review automatically when a decision is recorded.")  # fmt: skip
    if not allowed:
        reopen = st.text_input("Rationale to reopen", key="reopen_rationale")
        if st.button("Reopen for review"):
            _decide(card.card_id, ReviewAction.REOPEN, user, role, reopen, None, None)  # type: ignore[attr-defined]
        return
    with st.form("review_form"):
        owner = st.text_input("Accountable owner (required to approve)", value=card.owner or "")  # type: ignore[attr-defined]
        proposed = st.text_input("Proposed action", value=card.proposed_action or "Commission supplier scan")  # type: ignore[attr-defined]
        rationale = st.text_area("Rationale (required for Watchlist / Reject)")
        cols = st.columns(3)
        approve = cols[0].form_submit_button("✅ Approve", type="primary", disabled=ReviewAction.APPROVE not in allowed)
        watch = cols[1].form_submit_button("👀 Watchlist", disabled=ReviewAction.WATCHLIST not in allowed)
        reject = cols[2].form_submit_button("⛔ Reject", disabled=ReviewAction.REJECT not in allowed)
    action = (
        ReviewAction.APPROVE
        if approve
        else ReviewAction.WATCHLIST
        if watch
        else ReviewAction.REJECT
        if reject
        else None
    )
    if action is not None:
        _decide(card.card_id, action, user, role, rationale, owner or None, proposed or None)  # type: ignore[attr-defined]


def _decide(
    card_id: str,
    action: ReviewAction,
    user: str,
    role: str,
    rationale: str | None,
    owner: str | None,
    proposed: str | None,
) -> None:
    app = get_app()
    try:
        out = app.lifecycle.review(card_id, action, reviewer=user, role=role, rationale=rationale or None, owner=owner,
                                   proposed_action=proposed)  # fmt: skip
        st.session_state["flash"] = (
            "ok",
            f"{action.value}: card is now {out.card.status.value} (recorded for {user}, audited).",
        )
    except PolicyViolation as exc:
        st.session_state["flash"] = ("err", f"Permission denied: {exc.decision.reason}. Switch role in the sidebar.")
    except LifecycleError as exc:
        st.session_state["flash"] = ("err", str(exc))
    st.rerun()


# 7. Platform Health & Governance ---------------------------------------------------------------
def platform_health() -> None:
    app = get_app()
    p = app.platform
    st.title("Platform Health & Governance")
    ok, n_events = p.audit.verify_chain()
    runs = p.runtime.list_runs(100)
    denied = p.policy.decisions(allowed=False, limit=200)
    c = st.columns(5)
    c[0].metric("Kill switch", "ENGAGED" if p.kill_switch.engaged() else "released")
    c[1].metric("Audit chain", "valid" if ok else "BROKEN", f"{n_events} events", delta_color="off")
    c[2].metric("Runs", len(runs), f"{sum(r.status.value == 'SUCCEEDED' for r in runs)} succeeded", delta_color="off")
    c[3].metric("Policy denials", len(denied))
    c[4].metric("Dead letters", len(p.runtime.dead_letters(200)))
    tabs = st.tabs(["Runs & traces", "Costs", "Capabilities", "Policy decisions", "Evaluations", "Audit log"])
    with tabs[0]:
        st.dataframe(df([{"run": r.run_id, "status": r.status.value, "market": r.request.get("market"), "tier": r.request.get("tier"),
                          "created": r.created_at.strftime("%Y-%m-%d %H:%M:%S"), "cost USD": r.actual_cost_usd,
                          "estimate USD": r.cost_estimate.total_usd if r.cost_estimate else None, "resumed": r.resumed_count,
                          "failure": r.failure_class or "", "trace": r.trace_id} for r in runs]),
                     hide_index=True, width="stretch")  # fmt: skip
        if runs:
            rid = st.selectbox("Trace for run", [r.run_id for r in runs])
            run = p.runtime.get(rid)
            if run and run.trace_id:
                spans = p.telemetry.spans_for_trace(run.trace_id)
                depth_max = st.slider("Span depth", 0, 5, 1)
                rows = [{"span": "\u2003" * d + s["name"], "ms": s["duration_ms"], "status": s["status"],
                         "attributes": json.dumps({k: v for k, v in s["attributes"].items() if k not in ("tenant.id",)}, default=str)[:160]}
                        for d, s in span_tree(spans) if d <= depth_max]  # fmt: skip
                st.caption(f"trace {run.trace_id} · {len(spans)} spans (OpenTelemetry, W3C trace context)")
                st.dataframe(df(rows), hide_index=True, width="stretch", height=360)
                st.dataframe(df([{"step": s.name, "status": s.status.value, "attempts": s.attempts, "ms": s.duration_ms,
                                  "checkpoint": s.restored_from_checkpoint, "error": s.error or ""} for s in run.steps]),
                             hide_index=True, width="stretch")  # fmt: skip
    with tabs[1]:
        costs = p.costs.breakdown()
        if costs:
            cdf = pd.DataFrame(costs)
            st.altair_chart(alt.Chart(cdf).mark_bar().encode(x="usd:Q", y=alt.Y("capability_id:N", sort="-x"), color="category:N")
                            .properties(height=260), width="stretch")  # fmt: skip
            st.dataframe(cdf, hide_index=True, width="stretch")
    with tabs[2]:
        revoked = p.registry.revoked()
        rows = []
        for m in p.registry.all():
            ex, reason = p.registry.executable_status(m.capability_id, app.settings.env)
            rows.append({"capability": m.capability_id, "version": m.version, "kind": m.kind.value, "status": m.status.value,
                         "revoked": revoked.get(m.capability_id, ""), "executable": "✅" if ex else f"❌ {reason}",
                         "tools": ", ".join(m.allowed_tools), "egress": ", ".join(m.network_policy.outbound_allowlist) or "none",
                         "models": ", ".join(m.model_policy.allowed_models) if m.model_policy else "", "max steps": m.max_steps,
                         "max cost USD": m.max_cost_usd, "owner": m.owner})  # fmt: skip
        st.dataframe(df(rows), hide_index=True, width="stretch")
    with tabs[3]:
        decisions = p.policy.decisions(limit=300)
        summary = Counter((d.action, d.allowed) for d in decisions)
        st.dataframe(df([{"action": a, "allowed": al, "count": n} for (a, al), n in sorted(summary.items())]),
                     hide_index=True, width="stretch")  # fmt: skip
        st.markdown("**Recent denials**")
        st.dataframe(df([{"when": d.decided_at.strftime("%Y-%m-%d %H:%M:%S"), "subject": d.subject, "action": d.action,
                          "resource": d.resource, "reason": d.reason} for d in denied[:50]]),
                     hide_index=True, width="stretch")  # fmt: skip
    with tabs[4]:
        from hop.platform.evaluation import EvaluationHarness

        hist = EvaluationHarness(p.store, p.telemetry, p.audit).history(limit=20)
        if not hist:
            st.info("No evaluation runs yet: `hop evaluation run`.")
        st.dataframe(df([{"suite": h.suite_id, "passed": "✅" if h.passed else "❌", "n": h.n_cases, "partition": h.partition,
                          **dict(h.metrics.items()), "when": h.started_at.strftime("%Y-%m-%d %H:%M")} for h in hist]),
                     hide_index=True, width="stretch")  # fmt: skip
        st.caption("Golden sets are small development partitions; ratchet thresholds become binding only after validation "
                   "on representative labelled data.")  # fmt: skip
    with tabs[5]:
        events = p.audit.list(limit=100)
        st.dataframe(df([{"when": e.occurred_at.strftime("%Y-%m-%d %H:%M:%S"), "actor": e.actor, "type": e.actor_type.value,
                          "action": e.action, "resource": f"{e.resource_type}:{e.resource_id}", "outcome": e.outcome,
                          "hash": (e.event_hash or "")[:12]} for e in events]), hide_index=True, width="stretch")  # fmt: skip


PAGES = [
    (executive_portfolio, "Executive Portfolio", "📊"),
    (consumer_need_explorer, "Consumer Need Explorer", "🧭"),
    (serp_landscape, "SERP Landscape", "🔎"),
    (gerp_landscape, "GERP Landscape", "🤖"),
    (gap_matrix, "SERP–GERP Gap Matrix", "🧩"),
    (evidence_room, "Opportunity Evidence Room", "🗂️"),
    (platform_health, "Platform Health & Governance", "🛡️"),
]
