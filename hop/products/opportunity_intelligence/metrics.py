"""Deterministic visibility, recommendation, source and quality metrics per (market, need) and brand.

Every rate is a ``Proportion`` (n + Wilson CI). Missing inputs yield explicit missing states.
Mentions, recommendations and exclusions are counted separately; an excluded brand is never counted
positively (per-answer label precedence EXCLUSION > PRIMARY > SUPPORTING > MENTION).
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any
from urllib.parse import urlsplit

from hop.platform.analytics.stats import hhi
from hop.platform.common_contracts import MeasuredValue, Observation, Proportion, SignalFamily, ValueState, utcnow
from hop.platform.workflow_runtime import RunContext
from hop.products.opportunity_intelligence.deps import DiscoveryDeps
from hop.products.opportunity_intelligence.normalisation import strongest_label

OBSERVED = (ValueState.OBSERVED_VALUE, ValueState.OBSERVED_ZERO)
RECOMMEND = ("PRIMARY_RECOMMENDATION", "SUPPORTING_RECOMMENDATION")

METRIC_DEFINITIONS: dict[str, str] = {
    "demand.search_volume": "Sum of monthly Google search volume across the need's queries with observed volume.",
    "demand.coverage": "Share of the need's demand queries whose volume was observed (not missing).",
    "demand.index": "min(1, log10(volume+1) / log10(market reference volume+1)); reference set per market.",
    "demand.trend_yoy": "Volume-weighted change between the latest month and 12 months earlier.",
    "serp.supply_share": "Top-10 organic results that are on-need product pages from manufacturers/retailers/marketplaces.",
    "serp.top3_supply_share": "Top-3 organic results that are on-need product supply pages.",
    "serp.domain_diversity": "Unique domains among top-10 organic results.",
    "serp.shopping_feature_rate": "Queries whose SERP shows a shopping (product) feature.",
    "serp.paa_rate": "Queries whose SERP shows a People-Also-Ask feature.",
    "serp.brand_mentions": "Number of (result, brand) associations in top-10 organic results.",
    "serp.brand_hhi": "Herfindahl-Hirschman index of brand visibility in top-10 results (0-1).",
    "serp.volatility": "Rank volatility across repeated SERP snapshots.",
    "serp.brand_share": "Top-10 organic results associated with the brand.",
    "gerp.answers": "Number of generative answers observed for the need (all repeats).",
    "gerp.recommendation_coverage": "Answers giving at least one primary or supporting product recommendation.",
    "gerp.primary_rate": "Answers with a primary recommendation.",
    "gerp.mention_only_rate": "Answers naming brands without recommending any.",
    "gerp.exclusion_rate": "Answers that explicitly exclude at least one brand.",
    "gerp.citation_support": "Cited URLs whose domain also appears in the same query's top-10 SERP.",
    "gerp.stability": "Mean share of repeats agreeing on the modal primary brand (per query).",
    "gerp.brand_hhi": "HHI of recommendations across brands.",
    "gerp.brand_recommendation_rate": "Answers recommending the brand (primary or supporting, not excluded).",
    "gerp.brand_primary_rate": "Answers giving the brand as primary recommendation.",
    "gerp.brand_mention_rate": "Answers merely mentioning the brand.",
    "gerp.brand_exclusion_rate": "Answers explicitly excluding the brand.",
    "quality.entity_ambiguity_rate": "Ambiguous alias hits / all alias hits (SERP + GERP).",
    "quality.freshness_days": "Age in days of the oldest observation used.",
    "quality.freshness_ratio": "freshness_days / market freshness policy (>1 is stale).",
    "quality.min_sample_n": "Smallest sample size among the key rates.",
    "need.strategic_relevance": "Domain-steward rating of HKTDC strategic relevance (0-1).",
    "need.feasibility": "Domain-steward rating of supplier feasibility (0-1).",
    "need.regulatory_flag": "1 if the need carries regulatory/safety flags (e.g. health claims).",
}


def _missing_from(states: Counter[str], family: str) -> ValueState:
    for s in (
        ValueState.PROVIDER_ERROR,
        ValueState.PARSING_FAILED,
        ValueState.SUPPRESSED_BY_POLICY,
        ValueState.NOT_COLLECTED,
    ):
        if states.get(s.value):
            return s
    return ValueState.NOT_COLLECTED


def dump(metrics: dict[str, MeasuredValue | Proportion]) -> dict[str, Any]:
    return {k: v.model_dump(mode="json") for k, v in metrics.items()}


def compute_metrics(ctx: RunContext) -> dict[str, Any]:
    deps: DiscoveryDeps = ctx.deps
    pack, repo = deps.pack, deps.repo
    req_market = ctx.request["market"]
    market = pack.market(req_market)
    obs_all = repo.observations(ctx.run_id)
    mentions = repo.mentions(ctx.run_id)
    by_need: dict[str, list[Observation]] = {}
    for o in obs_all:
        by_need.setdefault(o.need_id, []).append(o)
    now = utcnow()
    records: list[dict[str, Any]] = []
    for need_id, obs in sorted(by_need.items()):
        need = pack.needs[need_id]
        m: dict[str, MeasuredValue | Proportion] = {}
        # demand ----------------------------------------------------------------------------
        demand = [o for o in obs if o.signal_family == SignalFamily.DEMAND]
        d_obs = [o for o in demand if o.status in OBSERVED]
        d_states = Counter(o.status.value for o in demand)
        if demand:
            m["demand.coverage"] = MeasuredValue.observed(round(len(d_obs) / len(demand), 4), n=len(demand))
        if d_obs:
            vol = sum(int(o.payload.get("search_volume") or 0) for o in d_obs)
            m["demand.search_volume"] = MeasuredValue.observed(vol, n=len(d_obs), unit="searches/month")
            idx = min(1.0, math.log10(vol + 1) / math.log10(market.demand_reference_volume + 1))
            m["demand.index"] = MeasuredValue.observed(round(idx, 4), n=len(d_obs))
            trends = [(o.payload.get("trend_yoy"), o.payload.get("search_volume") or 0) for o in d_obs]
            trends = [(t, w) for t, w in trends if t is not None]
            if trends and sum(w for _, w in trends) > 0:
                tw = sum(t * w for t, w in trends) / sum(w for _, w in trends)
                m["demand.trend_yoy"] = MeasuredValue.observed(round(tw, 4), n=len(trends), unit="ratio")
            else:
                m["demand.trend_yoy"] = MeasuredValue.missing(ValueState.INSUFFICIENT_SAMPLE, "no monthly history")
        else:
            state = _missing_from(d_states, "demand") if demand else ValueState.NOT_COLLECTED
            reason = "; ".join(sorted({o.error or o.status.value for o in demand})) or "demand not requested"
            for k in ("demand.search_volume", "demand.index", "demand.trend_yoy"):
                m[k] = MeasuredValue.missing(state, reason)
        # serp ------------------------------------------------------------------------------
        serp = [o for o in obs if o.signal_family == SignalFamily.SERP]
        s_obs = [o for o in serp if o.status in OBSERVED]
        serp_domains_by_query: dict[str, set[str]] = {}
        brand_results: Counter[str] = Counter()
        organic_n = 0
        if s_obs:
            results = [r for o in s_obs for r in o.payload.get("organic", [])]
            organic_n = len(results)
            top3 = [r for o in s_obs for r in o.payload.get("organic", [])[:3]]
            m["serp.supply_share"] = Proportion.from_counts(sum(r["supply"] for r in results), organic_n)
            m["serp.top3_supply_share"] = Proportion.from_counts(sum(r["supply"] for r in top3), len(top3))
            m["serp.domain_diversity"] = Proportion.from_counts(len({r["domain"] for r in results}), organic_n)
            m["serp.shopping_feature_rate"] = Proportion.from_counts(
                sum("shopping" in o.payload.get("features", []) for o in s_obs), len(s_obs)
            )
            m["serp.paa_rate"] = Proportion.from_counts(
                sum("people_also_ask" in o.payload.get("features", []) for o in s_obs), len(s_obs)
            )
            for o in s_obs:
                serp_domains_by_query[o.query_id] = {
                    r["domain"].removeprefix("www.") for r in o.payload.get("organic", [])
                }
            ev = deps.platform.evidence.search(
                run_id=ctx.run_id, need_id=need_id, evidence_types=[_serp_type()], exclude_quarantined=False
            )
            for e in ev:
                for b in e.entity_refs:
                    brand_results[b] += 1
            total_brand = sum(brand_results.values())
            m["serp.brand_mentions"] = MeasuredValue.observed(total_brand, n=organic_n)
            m["serp.brand_hhi"] = (
                MeasuredValue.observed(hhi(brand_results), n=total_brand)
                if total_brand
                else MeasuredValue.missing(ValueState.INSUFFICIENT_SAMPLE, "no brand visibility observed")
            )
            m["serp.volatility"] = MeasuredValue.missing(
                ValueState.NOT_COLLECTED, "single SERP snapshot; repeated observations required for volatility"
            )
        else:
            state = _missing_from(Counter(o.status.value for o in serp), "serp") if serp else ValueState.NOT_COLLECTED
            reason = "; ".join(sorted({(o.error or o.status.value)[:120] for o in serp})) or "serp not requested"
            for k in (
                "serp.supply_share",
                "serp.top3_supply_share",
                "serp.domain_diversity",
                "serp.shopping_feature_rate",
                "serp.paa_rate",
            ):
                m[k] = Proportion.missing(state, reason)
            for k in ("serp.brand_mentions", "serp.brand_hhi", "serp.volatility"):
                m[k] = MeasuredValue.missing(state, reason)
        # gerp ------------------------------------------------------------------------------
        gerp = [o for o in obs if o.signal_family == SignalFamily.GERP]
        g_obs = [o for o in gerp if o.status in OBSERVED]
        g_mentions = [x for x in mentions if x["need_id"] == need_id and x["source"] == "gerp"]
        per_answer: dict[str, dict[str, str]] = {}
        for x in g_mentions:
            if x["resolution"] != "RESOLVED" or not x["entity_id"]:
                continue
            per_answer.setdefault(x["observation_id"], {}).setdefault(x["entity_id"], [])  # type: ignore[arg-type]
            per_answer[x["observation_id"]][x["entity_id"]].append(x["label"])  # type: ignore[union-attr]
        final = {
            oid: {b: strongest_label(labels) for b, labels in brands.items()}  # type: ignore[arg-type]
            for oid, brands in per_answer.items()
        }
        n_ans = len(g_obs)
        brand_counts: dict[str, Counter[str]] = {}
        if g_obs:
            m["gerp.answers"] = MeasuredValue.observed(n_ans, n=n_ans)
            rec = prim = mention_only = excl = 0
            for o in g_obs:
                labels = final.get(o.observation_id, {})
                vals = set(labels.values())
                rec += bool(vals & set(RECOMMEND))
                prim += "PRIMARY_RECOMMENDATION" in vals
                mention_only += bool(vals) and not (vals & set(RECOMMEND))
                excl += "EXCLUSION" in vals
                for b, lab in labels.items():
                    brand_counts.setdefault(b, Counter())[lab] += 1
            m["gerp.recommendation_coverage"] = Proportion.from_counts(rec, n_ans)
            m["gerp.primary_rate"] = Proportion.from_counts(prim, n_ans)
            m["gerp.mention_only_rate"] = Proportion.from_counts(mention_only, n_ans)
            m["gerp.exclusion_rate"] = Proportion.from_counts(excl, n_ans)
            supported = total_cites = 0
            for o in g_obs:
                domains = serp_domains_by_query.get(o.query_id)
                if domains is None:
                    continue
                for url in o.payload.get("citations", []):
                    total_cites += 1
                    supported += (urlsplit(url).hostname or "").lower().removeprefix("www.") in domains
            m["gerp.citation_support"] = (
                Proportion.from_counts(supported, total_cites)
                if total_cites
                else Proportion.missing(ValueState.INSUFFICIENT_SAMPLE, "no citations with a matching SERP observation")
            )
            by_query: dict[str, list[str]] = {}
            for o in g_obs:
                labels = final.get(o.observation_id, {})
                primary = sorted(b for b, lab in labels.items() if lab == "PRIMARY_RECOMMENDATION")
                by_query.setdefault(o.query_id, []).append(primary[0] if primary else "(none)")
            shares = [Counter(v).most_common(1)[0][1] / len(v) for v in by_query.values() if len(v) >= 2]
            m["gerp.stability"] = (
                MeasuredValue.observed(round(sum(shares) / len(shares), 4), n=sum(len(v) for v in by_query.values()))
                if shares
                else MeasuredValue.missing(
                    ValueState.INSUFFICIENT_SAMPLE, "repeated observations required for stability"
                )
            )
            rec_by_brand = Counter(
                {b: c["PRIMARY_RECOMMENDATION"] + c["SUPPORTING_RECOMMENDATION"] for b, c in brand_counts.items()}
            )
            rec_by_brand = Counter({b: v for b, v in rec_by_brand.items() if v > 0})
            m["gerp.brand_hhi"] = (
                MeasuredValue.observed(hhi(rec_by_brand), n=sum(rec_by_brand.values()))
                if rec_by_brand
                else MeasuredValue.missing(ValueState.INSUFFICIENT_SAMPLE, "no recommendations observed")
            )
        else:
            state = _missing_from(Counter(o.status.value for o in gerp), "gerp") if gerp else ValueState.NOT_COLLECTED
            reason = "; ".join(sorted({(o.error or o.status.value)[:120] for o in gerp})) or "gerp not requested"
            m["gerp.answers"] = MeasuredValue.missing(state, reason)
            for k in (
                "gerp.recommendation_coverage",
                "gerp.primary_rate",
                "gerp.mention_only_rate",
                "gerp.exclusion_rate",
                "gerp.citation_support",
            ):
                m[k] = Proportion.missing(state, reason)
            m["gerp.stability"] = MeasuredValue.missing(state, reason)
            m["gerp.brand_hhi"] = MeasuredValue.missing(state, reason)
        # quality & config --------------------------------------------------------------------
        need_mentions = [x for x in mentions if x["need_id"] == need_id]
        if need_mentions:
            amb = sum(x["resolution"] == "AMBIGUOUS" for x in need_mentions)
            m["quality.entity_ambiguity_rate"] = MeasuredValue.observed(
                round(amb / len(need_mentions), 4), n=len(need_mentions)
            )
        else:
            m["quality.entity_ambiguity_rate"] = MeasuredValue.missing(ValueState.NOT_APPLICABLE, "no entity mentions")
        observed_obs = [o for o in obs if o.status in OBSERVED]
        if observed_obs:
            age = max((now - o.observed_at).total_seconds() / 86400 for o in observed_obs)
            m["quality.freshness_days"] = MeasuredValue.observed(round(age, 4), n=len(observed_obs), unit="days")
            m["quality.freshness_ratio"] = MeasuredValue.observed(round(age / market.freshness_policy_days, 6))
        else:
            m["quality.freshness_days"] = MeasuredValue.missing(ValueState.NOT_COLLECTED, "no observations")
            m["quality.freshness_ratio"] = MeasuredValue.missing(ValueState.NOT_COLLECTED, "no observations")
        sample_ns = [
            v.n
            for k, v in m.items()
            if isinstance(v, Proportion)
            and v.is_observed
            and v.n is not None
            and k in ("serp.supply_share", "gerp.recommendation_coverage")
        ]
        m["quality.min_sample_n"] = (
            MeasuredValue.observed(min(sample_ns))
            if sample_ns
            else MeasuredValue.missing(ValueState.INSUFFICIENT_SAMPLE, "no key rates observed")
        )
        m["need.strategic_relevance"] = MeasuredValue.observed(need.strategic_relevance)
        m["need.feasibility"] = MeasuredValue.observed(need.feasibility)
        m["need.regulatory_flag"] = MeasuredValue.observed(1.0 if need.regulatory_flags else 0.0)
        records.append(
            {
                "scope": "need",
                "scope_id": need_id,
                "need_id": need_id,
                "brand_id": None,
                "market": req_market,
                "metrics": dump(m),
            }
        )
        # brand scope -------------------------------------------------------------------------
        brands = set(brand_results) | set(brand_counts)
        for b in sorted(brands):
            bm: dict[str, MeasuredValue | Proportion] = {}
            bm["serp.brand_share"] = (
                Proportion.from_counts(brand_results.get(b, 0), organic_n) if organic_n else m["serp.supply_share"]
            )
            if n_ans:
                c = brand_counts.get(b, Counter())
                bm["gerp.answers"] = MeasuredValue.observed(n_ans, n=n_ans)
                bm["gerp.brand_recommendation_rate"] = Proportion.from_counts(
                    c["PRIMARY_RECOMMENDATION"] + c["SUPPORTING_RECOMMENDATION"], n_ans
                )
                bm["gerp.brand_primary_rate"] = Proportion.from_counts(c["PRIMARY_RECOMMENDATION"], n_ans)
                bm["gerp.brand_mention_rate"] = Proportion.from_counts(c["MENTION"], n_ans)
                bm["gerp.brand_exclusion_rate"] = Proportion.from_counts(c["EXCLUSION"], n_ans)
            else:
                for k in (
                    "gerp.brand_recommendation_rate",
                    "gerp.brand_primary_rate",
                    "gerp.brand_mention_rate",
                    "gerp.brand_exclusion_rate",
                ):
                    bm[k] = m["gerp.recommendation_coverage"]
                bm["gerp.answers"] = m["gerp.answers"]
            records.append(
                {
                    "scope": "brand",
                    "scope_id": f"{need_id}:{b}",
                    "need_id": need_id,
                    "brand_id": b,
                    "market": req_market,
                    "metrics": dump(bm),
                }
            )
    repo.replace_metrics(ctx.run_id, req_market, records)
    return {
        "need_records": sum(r["scope"] == "need" for r in records),
        "brand_records": sum(r["scope"] == "brand" for r in records),
    }


def _serp_type() -> Any:
    from hop.platform.common_contracts import EvidenceType

    return EvidenceType.SERP_RESULT


def load_metrics(record: dict[str, Any]) -> dict[str, MeasuredValue | Proportion]:
    out: dict[str, MeasuredValue | Proportion] = {}
    for k, v in record["metrics"].items():
        out[k] = Proportion.model_validate(v) if v.get("kind") == "proportion" else MeasuredValue.model_validate(v)
    return out
