"""DataForSEO adapters (SERP Google Organic live/advanced and Google Ads search volume) and parsers.

The HTTP client is only constructed when ``DATAFORSEO_LOGIN`` / ``DATAFORSEO_PASSWORD`` are set.
Every request passes the ``dataforseo.*`` capability egress allowlist (``api.dataforseo.com``).
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

import httpx

from hop.platform.integrations import ProviderPermanentError, ProviderResponse, ProviderTransientError
from hop.platform.integrations.http import GovernedHttpClient
from hop.platform.policy_engine import KillSwitch, PolicyEngine

API_BASE = "https://api.dataforseo.com/v3"
SERP_ENDPOINT = "/serp/google/organic/live/advanced"
VOLUME_ENDPOINT = "/keywords_data/google_ads/search_volume/live"
SERP_PARSER_VERSION = "dfs-serp-parser-1.2.0"
VOLUME_PARSER_VERSION = "dfs-volume-parser-1.1.0"
SERP_PAYLOAD_SCHEMA = "dataforseo.serp.organic.advanced.v3"
VOLUME_PAYLOAD_SCHEMA = "dataforseo.keywords_data.google_ads.search_volume.v3"


class ParseError(ValueError):
    pass


def _check_envelope(body: dict[str, Any]) -> dict[str, Any]:
    status = body.get("status_code")
    if status != 20000:
        if isinstance(status, int) and status >= 50000:
            raise ProviderTransientError(f"DataForSEO {status}: {body.get('status_message')}")
        raise ProviderPermanentError(f"DataForSEO {status}: {body.get('status_message')}")
    tasks = body.get("tasks") or []
    if not tasks:
        raise ProviderPermanentError("DataForSEO response has no tasks")
    task = tasks[0]
    tstatus = task.get("status_code")
    if tstatus != 20000:
        if isinstance(tstatus, int) and tstatus >= 50000:
            raise ProviderTransientError(f"DataForSEO task {tstatus}: {task.get('status_message')}")
        raise ProviderPermanentError(f"DataForSEO task {tstatus}: {task.get('status_message')}")
    return task


def parse_serp(raw: bytes) -> dict[str, Any]:
    try:
        body = json.loads(raw)
        task = body["tasks"][0]
        result = (task.get("result") or [None])[0]
        if result is None:
            raise ParseError("no result")
        items = result.get("items") or []
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise ParseError(f"malformed SERP payload: {exc}") from exc
    organic, features, paa = [], [], []
    for idx, item in enumerate(items):
        itype = item.get("type")
        if itype == "organic":
            url = item.get("url") or ""
            if not url.startswith(("http://", "https://")):
                raise ParseError(f"organic item {idx} has invalid url")
            organic.append(
                {
                    "item_index": idx,
                    "rank": int(item.get("rank_group") or len(organic) + 1),
                    "rank_absolute": int(item.get("rank_absolute") or idx + 1),
                    "url": url,
                    "domain": (item.get("domain") or urlsplit(url).hostname or "").lower(),
                    "title": item.get("title") or "",
                    "snippet": item.get("description") or "",
                }
            )
        else:
            features.append(itype)
            if itype == "people_also_ask":
                paa.extend(el.get("title", "") for el in item.get("items") or [])
    return {
        "keyword": result.get("keyword"),
        "se_domain": result.get("se_domain"),
        "datetime": result.get("datetime"),
        "se_results_count": result.get("se_results_count"),
        "organic": organic,
        "features": sorted(set(features)),
        "people_also_ask": paa,
    }


def parse_search_volume(raw: bytes) -> dict[str, dict[str, Any]]:
    try:
        body = json.loads(raw)
        task = body["tasks"][0]
        results = task.get("result") or []
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise ParseError(f"malformed search-volume payload: {exc}") from exc
    out: dict[str, dict[str, Any]] = {}
    for r in results:
        kw = str(r.get("keyword", "")).strip().lower()
        if not kw:
            continue
        monthly = sorted(
            (m for m in r.get("monthly_searches") or [] if m.get("search_volume") is not None),
            key=lambda m: (m["year"], m["month"]),
        )
        out[kw] = {
            "search_volume": r.get("search_volume"),
            "competition": r.get("competition"),
            "cpc": r.get("cpc"),
            "monthly_searches": monthly,
        }
    return out


class DataForSEOClient:
    """Real DataForSEO client. Used only when credentials are configured."""

    name = "dataforseo"
    serp_capability = "dataforseo.serp.collect"
    demand_capability = "dataforseo.demand.collect"

    def __init__(
        self,
        *,
        policy: PolicyEngine,
        kill_switch: KillSwitch,
        login: str,
        password: str,
        run_id: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.policy = policy
        self.kill_switch = kill_switch
        self._auth = (login, password)
        self.run_id = run_id
        self.transport = transport

    def _post(self, capability_id: str, endpoint: str, payload: list[dict[str, Any]]) -> tuple[bytes, dict[str, Any]]:
        client = GovernedHttpClient(
            self.policy, capability_id, kill_switch=self.kill_switch, run_id=self.run_id, transport=self.transport
        )
        try:
            response = client.post(f"{API_BASE}{endpoint}", json=payload, auth=self._auth)
        except httpx.TimeoutException as exc:
            raise ProviderTransientError(f"DataForSEO timeout: {exc}") from exc
        except httpx.TransportError as exc:
            raise ProviderTransientError(f"DataForSEO transport error: {exc}") from exc
        finally:
            client.close()
        if response.status_code == 429 or response.status_code >= 500:
            raise ProviderTransientError(f"DataForSEO HTTP {response.status_code}")
        if response.status_code >= 400:
            raise ProviderPermanentError(f"DataForSEO HTTP {response.status_code}")
        raw = response.content
        task = _check_envelope(response.json())
        return raw, task


class DataForSEOSerpProvider(DataForSEOClient):
    capability_id = DataForSEOClient.serp_capability
    unit_cost_usd = 0.002

    def fetch_serp(
        self,
        *,
        market: str,
        query_id: str,
        keyword: str,
        location_code: int,
        language_code: str,
        device: str,
        depth: int,
    ) -> ProviderResponse:
        raw, task = self._post(
            self.capability_id,
            SERP_ENDPOINT,
            [
                {
                    "keyword": keyword,
                    "location_code": location_code,
                    "language_code": language_code,
                    "device": device,
                    "depth": depth,
                }
            ],
        )
        return ProviderResponse(
            provider=self.name,
            endpoint=SERP_ENDPOINT,
            raw=raw,
            task_id=task.get("id"),
            cost_usd=float(task.get("cost") or self.unit_cost_usd),
            simulated=False,
            status="ok",
        )


class DataForSEODemandProvider(DataForSEOClient):
    capability_id = DataForSEOClient.demand_capability
    unit_cost_usd = 0.075

    def fetch_search_volume(
        self, *, market: str, keywords: list[str], location_code: int, language_code: str
    ) -> ProviderResponse:
        raw, task = self._post(
            self.capability_id,
            VOLUME_ENDPOINT,
            [{"keywords": keywords, "location_code": location_code, "language_code": language_code}],
        )
        return ProviderResponse(
            provider=self.name,
            endpoint=VOLUME_ENDPOINT,
            raw=raw,
            task_id=task.get("id"),
            cost_usd=float(task.get("cost") or self.unit_cost_usd),
            simulated=False,
            status="ok",
        )
