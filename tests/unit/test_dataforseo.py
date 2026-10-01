from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from hop.bootstrap import App, ConfigurationError, provider_mode
from hop.platform.integrations import ProviderPermanentError, ProviderTransientError
from hop.platform.integrations.dataforseo import (
    DataForSEODemandProvider,
    DataForSEOSerpProvider,
    ParseError,
    parse_search_volume,
    parse_serp,
)
from hop.platform.policy_engine import PolicyViolation
from tests.conftest import make_settings

SERP_BODY = {
    "status_code": 20000,
    "tasks": [
        {
            "id": "task-1",
            "status_code": 20000,
            "cost": 0.002,
            "result": [
                {
                    "keyword": "wide toe box running shoes",
                    "se_domain": "google.com.hk",
                    "items": [
                        {"type": "organic", "rank_group": 1, "rank_absolute": 1, "url": "https://altrarunning.com/x",
                         "domain": "altrarunning.com", "title": "Altra Torin", "description": "Wide toe box"},
                        {"type": "people_also_ask", "items": [{"title": "Are Altra shoes wide?"}]},
                        {"type": "organic", "rank_group": 2, "rank_absolute": 3, "url": "https://example.org/blog",
                         "title": "Best wide shoes", "description": "Our picks"},
                    ],
                }
            ],
        }
    ],
}  # fmt: skip

VOLUME_BODY = {
    "status_code": 20000,
    "tasks": [
        {
            "id": "task-2",
            "status_code": 20000,
            "cost": 0.075,
            "result": [
                {"keyword": "Wide Toe Box Running Shoes", "search_volume": 880, "competition": "LOW", "cpc": 0.4,
                 "monthly_searches": [{"year": 2026, "month": 8, "search_volume": 900},
                                      {"year": 2026, "month": 7, "search_volume": 860}]},
                {"keyword": "budget running shoes", "search_volume": None, "monthly_searches": []},
            ],
        }
    ],
}  # fmt: skip


def _transport(status: int, body: dict | None, seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body or {})

    return httpx.MockTransport(handler)


def _serp(app: App, transport: httpx.BaseTransport) -> DataForSEOSerpProvider:
    p = app.platform
    return DataForSEOSerpProvider(
        policy=p.policy, kill_switch=p.kill_switch, login="user", password="pw", run_id="r1", transport=transport
    )


def _fetch(provider: DataForSEOSerpProvider):  # noqa: ANN202
    return provider.fetch_serp(
        market="HK", query_id="q", keyword="wide toe box running shoes", location_code=2344,
        language_code="en", device="mobile", depth=10,
    )  # fmt: skip


def test_parse_serp_keeps_ranks_and_features() -> None:
    parsed = parse_serp(json.dumps(SERP_BODY).encode())
    assert [o["rank"] for o in parsed["organic"]] == [1, 2]
    assert parsed["organic"][1]["domain"] == "example.org"
    assert parsed["features"] == ["people_also_ask"] and parsed["people_also_ask"] == ["Are Altra shoes wide?"]


def test_parse_serp_rejects_malformed_payloads() -> None:
    with pytest.raises(ParseError):
        parse_serp(b"not json")
    bad = json.loads(json.dumps(SERP_BODY))
    bad["tasks"][0]["result"][0]["items"][0]["url"] = "javascript:alert(1)"
    with pytest.raises(ParseError):
        parse_serp(json.dumps(bad).encode())


def test_parse_search_volume_preserves_null_as_missing() -> None:
    parsed = parse_search_volume(json.dumps(VOLUME_BODY).encode())
    assert parsed["wide toe box running shoes"]["search_volume"] == 880
    assert [m["month"] for m in parsed["wide toe box running shoes"]["monthly_searches"]] == [7, 8]
    assert parsed["budget running shoes"]["search_volume"] is None


def test_serp_request_is_governed(app: App) -> None:
    seen: list[httpx.Request] = []
    response = _fetch(_serp(app, _transport(200, SERP_BODY, seen)))
    assert response.task_id == "task-1" and response.cost_usd == 0.002 and not response.simulated
    [request] = seen
    assert request.url.host == "api.dataforseo.com" and request.headers["authorization"].startswith("Basic ")
    assert json.loads(request.content)[0]["location_code"] == 2344
    egress = [d for d in app.platform.policy.decisions() if d.action == "network.egress"]
    assert egress and egress[0].allowed


def test_demand_request(app: App) -> None:
    seen: list[httpx.Request] = []
    p = app.platform
    provider = DataForSEODemandProvider(
        policy=p.policy,
        kill_switch=p.kill_switch,
        login="u",
        password="p",
        transport=_transport(200, VOLUME_BODY, seen),
    )
    response = provider.fetch_search_volume(market="HK", keywords=["a"], location_code=2344, language_code="en")
    assert response.cost_usd == 0.075 and seen[0].url.path.endswith("/search_volume/live")


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (500, None, ProviderTransientError),
        (429, None, ProviderTransientError),
        (401, None, ProviderPermanentError),
        (200, {"status_code": 40100, "status_message": "auth"}, ProviderPermanentError),
        (200, {"status_code": 50000, "status_message": "internal"}, ProviderTransientError),
    ],
)
def test_error_classification(app: App, status: int, body: dict | None, error: type[Exception]) -> None:
    with pytest.raises(error):
        _fetch(_serp(app, _transport(status, body, [])))


def test_revoked_collector_cannot_call_out(app: App) -> None:
    app.platform.registry.revoke("dataforseo.serp.collect", "vendor incident")
    seen: list[httpx.Request] = []
    with pytest.raises(PolicyViolation):
        _fetch(_serp(app, _transport(200, SERP_BODY, seen)))
    assert seen == []


def test_provider_mode_selection(tmp_path: Path) -> None:
    offline = make_settings(tmp_path, serp_provider="auto")
    assert provider_mode(offline) == "sandbox"
    with pytest.raises(ConfigurationError):
        provider_mode(offline, "dataforseo")
    with pytest.raises(ConfigurationError):
        provider_mode(offline, "bing")
    online = make_settings(
        tmp_path, serp_provider="auto", dataforseo_login=SecretStr("u"), dataforseo_password=SecretStr("p")
    )
    assert provider_mode(online) == "dataforseo"
    assert provider_mode(online, "sandbox") == "sandbox"
