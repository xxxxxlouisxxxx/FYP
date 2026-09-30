from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hop.api import create_app
from tests.conftest import Discovery

ANALYST = {"X-HOP-User": "Sam Analyst", "X-HOP-Role": "analyst"}
BOARD = {"X-HOP-User": "Ada Chan", "X-HOP-Role": "review_board"}
VIEWER = {"X-HOP-User": "Vic Viewer", "X-HOP-Role": "viewer"}


@pytest.fixture
def client(fresh_discovery: Discovery) -> TestClient:
    return TestClient(create_app(fresh_discovery.app))


def test_health(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["audit_chain_valid"] and body["kill_switch"] is False


def test_opportunities_and_rbac(client: TestClient, fresh_discovery: Discovery) -> None:
    cards = client.get("/opportunities", headers=VIEWER).json()
    assert cards and {c["status"] for c in cards} == {"DRAFT"}
    card_id = cards[0]["card_id"]
    detail = client.get(f"/opportunities/{card_id}", headers=VIEWER).json()
    assert detail["card"]["supporting_evidence_ids"] and "SUBMIT_FOR_REVIEW" in detail["allowed_actions"]
    assert client.get(f"/opportunities/{card_id}/evidence", headers=VIEWER).status_code == 403
    assert client.get(f"/opportunities/{card_id}/evidence", headers=ANALYST).status_code == 200
    assert client.get("/opportunities/nope", headers=VIEWER).status_code == 404
    assert client.post("/runs", json={"market": "HK"}, headers=VIEWER).status_code == 403
    assert client.get("/runs", headers={"X-HOP-Role": "intruder"}).status_code == 403


def test_evidence_lineage_and_raw_access(client: TestClient, fresh_discovery: Discovery) -> None:
    card = fresh_discovery.app.repo.cards(run_id=fresh_discovery.run.run_id)[0]
    eid = card.supporting_evidence_ids[0]
    body = client.get(f"/evidence/{eid}", headers=ANALYST).json()
    assert body["lineage"] == {"valid": True, "reason": "ok"}
    assert client.get(f"/evidence/{eid}/raw", headers=VIEWER).status_code == 403
    raw = client.get(f"/evidence/{eid}/raw", headers=ANALYST).json()
    assert raw["untrusted_content"] is True and raw["sha256"] == body["evidence"]["content_hash"]


def test_traceparent_is_continued(client: TestClient) -> None:
    trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    headers = {**ANALYST, "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01"}
    response = client.get("/runs", headers=headers)
    assert response.status_code == 200
    assert trace_id in response.headers.get("traceparent", "")
    trace = client.get(f"/traces/{trace_id}", headers=ANALYST).json()
    assert any(s["name"] == "API GET /runs" for s in trace["spans"])


def test_review_flow_over_http(client: TestClient, fresh_discovery: Discovery) -> None:
    high = next(c for c in fresh_discovery.app.repo.cards(run_id=fresh_discovery.run.run_id) if c.priority == "HIGH")
    url = f"/opportunities/{high.card_id}/review"
    r = client.post(url, json={"action": "APPROVE", "owner": "Desk"}, headers=ANALYST)
    assert r.status_code == 403
    r = client.post(url, json={"action": "APPROVE", "owner": "Desk"}, headers={"X-HOP-Role": "review_board"})
    assert r.status_code == 422, "anonymous reviewers are rejected"
    r = client.post(url, json={"action": "APPROVE", "owner": "Sourcing Desk HK"}, headers=BOARD)
    assert r.status_code == 200 and r.json()["status"] == "APPROVED"
    r = client.post(url, json={"action": "REJECT", "rationale": "x"}, headers=BOARD)
    assert r.status_code == 409


def test_estimate_create_run_and_export(client: TestClient) -> None:
    est = client.post("/runs/estimate", json={"market": "SG"}, headers=ANALYST).json()
    assert est["within_budget"] and est["total_usd"] > 0
    run = client.post("/runs", json={"market": "SG", "force_new": True}, headers=ANALYST)
    assert run.status_code == 201 and run.json()["status"] == "SUCCEEDED" and run.json()["cards"]
    assert client.get(f"/runs/{run.json()['run_id']}", headers=VIEWER).json()["costs"]
    assert client.post("/runs", json={"market": "HK", "provider": "dataforseo"}, headers=ANALYST).status_code == 422
    exported = client.get("/opportunities/export?fmt=csv", headers=ANALYST)
    assert exported.status_code == 200 and exported.text.startswith("card_id,")
    assert exported.headers["X-HOP-Export-URI"]


def test_governance_endpoints(client: TestClient) -> None:
    caps = client.get("/capabilities", headers=ANALYST).json()
    assert {"opportunity.scoring", "experimental.web_browse"} <= {c["capability_id"] for c in caps}
    assert client.get("/audit", headers=ANALYST).json()["chain_valid"]
    assert isinstance(client.get("/policy/decisions", headers=ANALYST).json(), list | dict)
    assert client.get("/costs", headers=ANALYST).status_code == 200
