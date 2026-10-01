"""Parse and normalise raw payloads, resolve entities, create immutable evidence, run data-quality checks."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from hop.platform.common_contracts import (
    CostAttribution,
    DataQualityStatus,
    EvidenceItem,
    EvidenceType,
    Observation,
    RetentionClass,
    SignalFamily,
    SourceSpan,
    ValueState,
    sha256_hex,
    stable_id,
)
from hop.platform.entity_resolution import ResolutionStatus
from hop.platform.evidence_service.object_store import ObjectStoreError
from hop.platform.integrations.dataforseo import (
    SERP_PAYLOAD_SCHEMA,
    VOLUME_PAYLOAD_SCHEMA,
    ParseError,
    parse_search_volume,
    parse_serp,
)
from hop.platform.policy_engine.content_safety import detect_injection
from hop.platform.workflow_runtime import RunContext
from hop.products.opportunity_intelligence.deps import DiscoveryDeps

SUPPLY_SOURCE_TYPES = {"manufacturer", "retailer", "marketplace"}
LABEL_PRECEDENCE = ["EXCLUSION", "PRIMARY_RECOMMENDATION", "SUPPORTING_RECOMMENDATION", "MENTION"]
LABEL_EVIDENCE = {
    "PRIMARY_RECOMMENDATION": EvidenceType.GERP_PRIMARY_RECOMMENDATION,
    "SUPPORTING_RECOMMENDATION": EvidenceType.GERP_SUPPORTING_RECOMMENDATION,
    "MENTION": EvidenceType.GERP_MENTION,
    "EXCLUSION": EvidenceType.GERP_EXCLUSION,
}
GERP_PAYLOAD_SCHEMA = "model_gateway.gerp_answer_v1"


def strongest_label(labels: list[str]) -> str:
    return min(labels, key=LABEL_PRECEDENCE.index)


def matches_terms(text: str, terms: list[str]) -> bool:
    low = text.lower()
    for term in terms:
        t = term.lower()
        if all(ord(c) < 128 for c in t):
            if re.search(rf"(?<![\w]){re.escape(t)}(?![\w])", low):
                return True
        elif t in low:
            return True
    return False


def _evidence(
    obs: Observation,
    *,
    key: tuple[Any, ...],
    etype: EvidenceType,
    claim: str,
    payload_schema: str,
    span: SourceSpan | None = None,
    entity_refs: tuple[str, ...] = (),
    attributes: dict[str, Any] | None = None,
    flags: tuple[str, ...] = (),
    dq: DataQualityStatus = DataQualityStatus.PASSED,
    cost_share: float = 0.0,
    retention: RetentionClass = RetentionClass.RAW_PROVIDER_90D,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=stable_id("ev", obs.run_id, etype.value, obs.observation_id, *key),
        evidence_type=etype,
        source_provider=obs.provider,
        source_endpoint=obs.endpoint,
        market=obs.market,
        locale=obs.locale,
        language=obs.language,
        device=obs.device,
        query_id=obs.query_id,
        prompt_id=obs.prompt_id,
        observed_at=obs.observed_at,
        raw_payload_uri=obs.raw_artifact_uri or "",
        content_hash=obs.content_hash or "0" * 64,
        parser_version=obs.parser_version or "unknown",
        payload_schema_version=payload_schema,
        model_id=obs.model_id,
        prompt_version=obs.prompt_version,
        extracted_claim=claim,
        source_span=span,
        entity_refs=tuple(sorted(set(entity_refs))),
        data_quality_status=dq,
        quality_flags=flags,
        retention_class=retention,
        cost_attribution=CostAttribution(
            usd=round(cost_share, 8), unit="share_of_observation", simulated=obs.simulated
        ),
        trace_id=obs.trace_id,
        run_id=obs.run_id,
        observation_id=obs.observation_id,
        need_id=obs.need_id,
        attributes=attributes or {},
        untrusted_content=True,
    )


# 9. parse & normalise -------------------------------------------------------------------------
def normalise(ctx: RunContext) -> dict[str, Any]:
    deps: DiscoveryDeps = ctx.deps
    pack, repo, evidence = deps.pack, deps.repo, deps.platform.evidence
    parsed_cache: dict[str, Any] = {}
    counts: dict[str, int] = {}
    created = 0
    with ctx.span("Parsing", {"parser": "dataforseo"}):
        for obs in repo.observations(ctx.run_id):
            if obs.signal_family == SignalFamily.GERP or obs.status != ValueState.OBSERVED_VALUE:
                counts[obs.status.value] = counts.get(obs.status.value, 0) + 1
                continue
            raw_uri = obs.raw_artifact_uri or ""
            try:
                if obs.signal_family == SignalFamily.DEMAND:
                    if raw_uri not in parsed_cache:
                        parsed_cache[raw_uri] = parse_search_volume(evidence.read_raw(raw_uri))
                    row = parsed_cache[raw_uri].get(obs.query_text.strip().lower())
                    obs, ev = _normalise_demand(obs, row)
                    if ev is not None:
                        evidence.add(ev)
                        created += 1
                else:
                    parsed = parse_serp(evidence.read_raw(raw_uri))
                    obs = _normalise_serp(obs, parsed, pack, deps)
            except (ParseError, ObjectStoreError) as exc:
                obs = obs.model_copy(update={"status": ValueState.PARSING_FAILED, "error": str(exc)[:500]})
            repo.upsert_observation(obs)
            counts[obs.status.value] = counts.get(obs.status.value, 0) + 1
    return {"by_status": counts, "evidence_created": created}


def _normalise_demand(obs: Observation, row: dict[str, Any] | None) -> tuple[Observation, EvidenceItem | None]:
    if row is None:
        return obs.model_copy(
            update={"status": ValueState.NOT_COLLECTED, "error": "keyword absent from provider response"}
        ), None
    volume = row.get("search_volume")
    monthly = row.get("monthly_searches") or []
    trend = None
    if len(monthly) >= 12 and monthly[0]["search_volume"]:
        trend = round(monthly[-1]["search_volume"] / monthly[0]["search_volume"] - 1, 4)
    payload = {
        "search_volume": volume,
        "trend_yoy": trend,
        "monthly": monthly,
        "competition": row.get("competition"),
        "cpc": row.get("cpc"),
    }
    if volume is None:
        return obs.model_copy(
            update={
                "status": ValueState.NOT_COLLECTED,
                "payload": payload,
                "error": "provider returned null search volume",
            }
        ), None
    status = ValueState.OBSERVED_ZERO if volume == 0 else ValueState.OBSERVED_VALUE
    obs = obs.model_copy(update={"status": status, "payload": payload})
    trend_txt = f"; 12-month trend {trend:+.0%}" if trend is not None else ""
    ev = _evidence(
        obs,
        key=("volume",),
        etype=EvidenceType.DEMAND_SIGNAL,
        claim=f"Monthly Google search volume for '{obs.query_text}' in {obs.market} ({obs.language}): {volume:,}{trend_txt}",
        payload_schema=VOLUME_PAYLOAD_SCHEMA,
        span=SourceSpan(
            field=f"tasks[0].result[keyword='{obs.query_text}'].search_volume",
            start=0,
            end=len(str(volume)),
            text=str(volume),
        ),
        attributes={"search_volume": volume, "trend_yoy": trend, "query_text": obs.query_text},
        cost_share=obs.cost_usd,
    )
    return obs, ev


def _normalise_serp(obs: Observation, parsed: dict[str, Any], pack: Any, deps: DiscoveryDeps) -> Observation:
    need = pack.needs[obs.need_id]
    organic = []
    flagged = False
    for item in parsed["organic"][:10]:
        text = f"{item['title']} {item['snippet']}"
        source_type = pack.source_type(item["domain"])
        on_need = matches_terms(text, need.match_terms)
        injection = [f.pattern for f in detect_injection(text)]
        flagged = flagged or bool(injection)
        organic.append(
            {
                **item,
                "source_type": source_type,
                "on_need": on_need,
                "supply": on_need and source_type in SUPPLY_SOURCE_TYPES,
                "injection_findings": injection,
            }
        )
    flags = sorted(set(obs.quality_flags) | ({"PROMPT_INJECTION_SUSPECTED"} if flagged else set()))
    status = ValueState.OBSERVED_VALUE if organic else ValueState.OBSERVED_ZERO
    payload = {
        "organic": organic,
        "features": parsed["features"],
        "people_also_ask": parsed["people_also_ask"],
        "se_domain": parsed["se_domain"],
        "provider_datetime": parsed["datetime"],
    }
    return obs.model_copy(update={"status": status, "payload": payload, "quality_flags": flags})


# 10. entity resolution + evidence extraction ------------------------------------------------------
def resolve_entities(ctx: RunContext) -> dict[str, Any]:
    deps: DiscoveryDeps = ctx.deps
    repo, evidence, resolver = deps.repo, deps.platform.evidence, deps.resolver
    domain_owner = {d.lower(): e.entity_id for e in resolver.entities.values() for d in e.domains}
    mentions: list[dict[str, Any]] = []
    items: list[EvidenceItem] = []
    stats = {"resolved": 0, "ambiguous": 0, "unresolved": 0, "span_mismatch": 0}
    for obs in repo.observations(ctx.run_id):
        if obs.status not in (ValueState.OBSERVED_VALUE, ValueState.OBSERVED_ZERO):
            continue
        if obs.signal_family == SignalFamily.SERP:
            for pos, item in enumerate(obs.payload.get("organic", [])):
                text = f"{item['title']}\n{item['snippet']}"
                brands: set[str] = set()
                ambiguous = 0
                for hit in resolver.scan(text):
                    status = hit.resolution.status
                    stats[status.value.lower()] += 1
                    if status == ResolutionStatus.RESOLVED and hit.resolution.entity_id:
                        brands.add(hit.resolution.entity_id)
                    elif status == ResolutionStatus.AMBIGUOUS:
                        ambiguous += 1
                    mentions.append(
                        _mention(
                            obs,
                            "serp",
                            hit.surface,
                            hit.resolution,
                            hit.start,
                            hit.end,
                            None,
                            rank=item["rank"],
                            item=pos,
                        )
                    )
                dom = item["domain"].removeprefix("www.")
                if dom in domain_owner:
                    brands.add(domain_owner[dom])
                flags = ("PROMPT_INJECTION_SUSPECTED", "UNTRUSTED_CONTENT") if item["injection_findings"] else ()
                items.append(
                    _evidence(
                        obs,
                        key=("organic", pos),
                        etype=EvidenceType.SERP_RESULT,
                        claim=(
                            f"Rank {item['rank']} for '{obs.query_text}' ({obs.market}): \"{item['title']}\" "
                            f"[{item['domain']}, {item['source_type']}{', on-need product supply' if item['supply'] else ''}]"
                        ),
                        payload_schema=SERP_PAYLOAD_SCHEMA,
                        span=SourceSpan(
                            field=f"tasks[0].result[0].items[{item['item_index']}].title",
                            start=0,
                            end=len(item["title"]),
                            text=item["title"],
                        ),
                        entity_refs=tuple(brands),
                        attributes={
                            "rank": item["rank"],
                            "domain": item["domain"],
                            "url": item["url"],
                            "source_type": item["source_type"],
                            "on_need": item["on_need"],
                            "supply": item["supply"],
                            "ambiguous_mentions": ambiguous,
                            "injection_findings": item["injection_findings"],
                        },
                        flags=flags,
                        dq=DataQualityStatus.QUARANTINED if flags else DataQualityStatus.PASSED,
                        cost_share=obs.cost_usd / max(1, len(obs.payload.get("organic", []))),
                    )
                )
        elif obs.signal_family == SignalFamily.GERP:
            answer = obs.payload.get("answer_text", "")
            injected = "PROMPT_INJECTION_SUSPECTED" in obs.quality_flags
            flags = ("PROMPT_INJECTION_SUSPECTED",) if injected else ()
            dq = DataQualityStatus.WARNING if injected else DataQualityStatus.PASSED
            per_brand: dict[str, list[str]] = {}
            label_items = []
            for idx, m in enumerate(obs.payload.get("extraction", {}).get("mentions", [])):
                start, end, surface = m["start"], m["end"], m["surface"]
                if answer[start:end] != surface:
                    stats["span_mismatch"] += 1
                    found = answer.find(surface)
                    if found < 0:
                        continue
                    start, end = found, found + len(surface)
                res = resolver.resolve(surface, answer, start, end)
                stats[res.status.value.lower()] += 1
                mentions.append(_mention(obs, "gerp", surface, res, start, end, m["label"], item=idx))
                if res.status != ResolutionStatus.RESOLVED or not res.entity_id:
                    continue
                per_brand.setdefault(res.entity_id, []).append(m["label"])
                s0 = max(0, answer.rfind(".", 0, start) + 1)
                e0 = answer.find(".", end)
                sentence = answer[s0 : (e0 + 1 if e0 >= 0 else len(answer))].strip()
                label_items.append(
                    _evidence(
                        obs,
                        key=("mention", idx),
                        etype=LABEL_EVIDENCE[m["label"]],
                        claim=f"{m['label'].replace('_', ' ').title()} of {resolver.name(res.entity_id)} in generative answer "
                        f"#{obs.repeat_index + 1} to '{obs.query_text}': \"{sentence[:220]}\"",
                        payload_schema=GERP_PAYLOAD_SCHEMA,
                        span=SourceSpan(field="answer_text", start=start, end=end, text=surface),
                        entity_refs=(res.entity_id,),
                        attributes={"label": m["label"], "repeat_index": obs.repeat_index, "sentence": sentence[:300]},
                        flags=flags,
                        dq=dq,
                        retention=RetentionClass.MODEL_OUTPUT_1Y,
                    )
                )
            final = {b: strongest_label(labels) for b, labels in per_brand.items()}
            recommended = sorted(
                b for b, lab in final.items() if lab in ("PRIMARY_RECOMMENDATION", "SUPPORTING_RECOMMENDATION")
            )
            items.extend(label_items)
            items.append(
                _evidence(
                    obs,
                    key=("answer",),
                    etype=EvidenceType.GERP_ANSWER,
                    claim=(
                        f"Generative answer #{obs.repeat_index + 1} ({obs.model_id}) to '{obs.query_text}' "
                        + (
                            f"recommends {', '.join(resolver.name(b) for b in recommended)}"
                            if recommended
                            else "gives no concrete product recommendation"
                        )
                    ),
                    payload_schema=GERP_PAYLOAD_SCHEMA,
                    span=SourceSpan(field="answer_text", start=0, end=min(len(answer), 240), text=answer[:240]),
                    entity_refs=tuple(final),
                    attributes={
                        "repeat_index": obs.repeat_index,
                        "brand_labels": final,
                        "has_recommendation": bool(recommended),
                        "primary_brands": sorted(b for b, lab in final.items() if lab == "PRIMARY_RECOMMENDATION"),
                        "citations": obs.payload.get("citations", []),
                    },
                    flags=flags,
                    dq=dq,
                    cost_share=obs.cost_usd,
                    retention=RetentionClass.MODEL_OUTPUT_1Y,
                )
            )
            for c_idx, url in enumerate(obs.payload.get("citations", [])):
                items.append(
                    _evidence(
                        obs,
                        key=("citation", c_idx),
                        etype=EvidenceType.GERP_CITATION,
                        claim=f"Generative answer #{obs.repeat_index + 1} to '{obs.query_text}' cites {url}",
                        payload_schema=GERP_PAYLOAD_SCHEMA,
                        span=SourceSpan(field=f"citations[{c_idx}]", start=0, end=len(url), text=url),
                        attributes={
                            "url": url,
                            "domain": (urlsplit(url).hostname or "").lower(),
                            "repeat_index": obs.repeat_index,
                        },
                        flags=flags,
                        dq=dq,
                        retention=RetentionClass.MODEL_OUTPUT_1Y,
                    )
                )
    with ctx.span("Evidence persistence", {"evidence.count": len(items)}):
        evidence.add_many(items)
    repo.replace_mentions(ctx.run_id, mentions)
    return {"mentions": len(mentions), "evidence_created": len(items), **stats, "resolver_version": resolver.version}


def _mention(
    obs: Observation,
    source: str,
    surface: str,
    res: Any,
    start: int,
    end: int,
    label: str | None,
    *,
    rank: int | None = None,
    item: int = 0,
) -> dict[str, Any]:
    return {
        "mention_id": stable_id("men", obs.observation_id, source, item, start, surface),
        "run_id": obs.run_id,
        "observation_id": obs.observation_id,
        "need_id": obs.need_id,
        "query_id": obs.query_id,
        "market": obs.market,
        "source": source,
        "repeat_index": obs.repeat_index,
        "surface": surface,
        "entity_id": res.entity_id,
        "resolution": res.status.value,
        "candidates": list(res.candidates),
        "confidence": res.confidence,
        "reason": res.reason,
        "label": label,
        "start": start,
        "end": end,
        "rank": rank,
        "item": item,
    }


# 11. data quality -------------------------------------------------------------------------------
def data_quality(ctx: RunContext) -> dict[str, Any]:
    deps: DiscoveryDeps = ctx.deps
    repo, evidence = deps.repo, deps.platform.evidence
    per_need: dict[str, dict[str, Any]] = {}
    hash_cache: dict[str, str] = {}
    critical = 0
    with ctx.span("Lineage verification"):
        for obs in repo.observations(ctx.run_id):
            need = per_need.setdefault(obs.need_id, {"families": {}, "flags": set(), "issues": []})
            fam = need["families"].setdefault(obs.signal_family.value, {"expected": 0, "observed": 0, "states": {}})
            fam["expected"] += 1
            fam["states"][obs.status.value] = fam["states"].get(obs.status.value, 0) + 1
            if obs.status in (ValueState.OBSERVED_VALUE, ValueState.OBSERVED_ZERO):
                fam["observed"] += 1
            need["flags"].update(obs.quality_flags)
            if obs.raw_artifact_uri:
                uri = obs.raw_artifact_uri
                if uri not in hash_cache:
                    try:
                        hash_cache[uri] = sha256_hex(evidence.read_raw(uri))
                    except ObjectStoreError:
                        hash_cache[uri] = "missing"
                if hash_cache[uri] != obs.content_hash:
                    need["flags"].add("HASH_MISMATCH")
                    need["issues"].append(f"raw payload hash mismatch for {obs.observation_id}")
                    critical += 1
    out: dict[str, Any] = {}
    for need_id, info in per_need.items():
        families = info["families"]
        if "HASH_MISMATCH" in info["flags"]:
            status = DataQualityStatus.FAILED_CRITICAL
        elif any(f["observed"] == 0 for f in families.values()):
            status = DataQualityStatus.FAILED_NON_CRITICAL
        elif any(f["observed"] < f["expected"] for f in families.values()) or info["flags"]:
            status = DataQualityStatus.WARNING
        else:
            status = DataQualityStatus.PASSED
        out[need_id] = {
            "status": status.value,
            "families": families,
            "flags": sorted(info["flags"]),
            "issues": info["issues"],
        }
    return {
        "needs": out,
        "critical_failures": critical,
        "status_counts": {
            s: sum(1 for v in out.values() if v["status"] == s) for s in {v["status"] for v in out.values()}
        },
    }
