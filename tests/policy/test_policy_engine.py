from __future__ import annotations

import pytest
from pydantic import BaseModel

from hop.bootstrap import App
from hop.platform.policy_engine import KillSwitchEngaged, PolicyViolation
from hop.platform.policy_engine.tools import AgentSession, MaxStepsExceeded, ToolArgumentError, ToolRegistry


class EchoArgs(BaseModel):
    text: str


def _tools() -> ToolRegistry:
    tools = ToolRegistry()
    tools.register("evidence.search", lambda a: {"echo": a.text}, EchoArgs)
    tools.register("object_store.export_write", lambda a: "written", EchoArgs)
    return tools


def _session(app: App, capability_id: str = "opportunity.evidence_retrieval") -> AgentSession:
    p = app.platform
    return AgentSession(
        policy=p.policy, tools=_tools(), telemetry=p.telemetry, capability_id=capability_id, run_id=None
    )


def test_tools_are_deny_by_default(app: App) -> None:
    session = _session(app)
    assert session.call("evidence.search", text="x") == {"echo": "x"}
    with pytest.raises(PolicyViolation) as exc:
        session.call("object_store.export_write", text="x")
    assert "deny-by-default" in exc.value.decision.reason
    denied = app.platform.policy.decisions(allowed=False)
    assert any(d.resource == "object_store.export_write" for d in denied)
    assert any(e.action == "policy.tool.invoke.denied" for e in app.platform.audit.list())


def test_tool_arguments_are_validated(app: App) -> None:
    with pytest.raises(ToolArgumentError):
        _session(app).call("evidence.search", nope=1)


def test_agent_step_limit(app: App) -> None:
    session = _session(app)
    for _ in range(session.manifest.max_steps):
        session.call("evidence.search", text="x")
    with pytest.raises(MaxStepsExceeded):
        session.call("evidence.search", text="x")


def test_draft_capability_cannot_execute(app: App) -> None:
    policy = app.platform.policy
    decision = policy.check_capability("experimental.web_browse")
    assert not decision.allowed and "draft" in decision.reason
    assert not policy.check_tool("experimental.web_browse", "http.get").allowed
    assert not policy.check_egress("experimental.web_browse", "https://example.com/").allowed


def test_unknown_capability_is_denied(app: App) -> None:
    assert not app.platform.policy.check_capability("does.not.exist").allowed


def test_revocation_blocks_and_reinstatement_restores(app: App) -> None:
    registry, policy = app.platform.registry, app.platform.policy
    registry.revoke("opportunity.scoring", "incident INC-1")
    decision = policy.check_capability("opportunity.scoring")
    assert not decision.allowed and "INC-1" in decision.reason
    registry.reinstate("opportunity.scoring")
    assert policy.check_capability("opportunity.scoring").allowed


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://api.dataforseo.com/v3/serp/google/organic/live/advanced", True),
        ("http://api.dataforseo.com/v3/serp", False),
        ("https://evil.example.com/v3", False),
        ("https://api.dataforseo.com.evil.com/", False),
        ("https://127.0.0.1/", False),
        ("https://169.254.169.254/latest/meta-data", False),
        ("https://localhost/", False),
        ("https://metadata.internal/", False),
        ("https://user:pw@api.dataforseo.com/", False),
        ("https://api.dataforseo.com:8443/", False),
    ],
)
def test_egress_allowlist(app: App, url: str, allowed: bool) -> None:
    assert app.platform.policy.check_egress("dataforseo.serp.collect", url).allowed is allowed


def test_sandbox_collectors_have_no_egress(app: App) -> None:
    assert not app.platform.policy.check_egress("sandbox.serp.collect", "https://api.dataforseo.com/").allowed


def test_model_allowlist(app: App) -> None:
    policy = app.platform.policy
    assert policy.check_model("gerp.observe", app.platform.gateway.default_model).allowed
    assert not policy.check_model("gerp.observe", "gpt-unlisted").allowed


def test_budget_check(app: App) -> None:
    policy = app.platform.policy
    assert policy.check_budget("gerp.observe", 0.001, 1.0).allowed
    assert not policy.check_budget("gerp.observe", 2.0, 1.0).allowed


@pytest.mark.parametrize(
    ("role", "permission", "allowed"),
    [
        ("viewer", "opportunity:read", True),
        ("viewer", "evidence:raw_read", False),
        ("viewer", "review:decide", False),
        ("analyst", "run:create", True),
        ("analyst", "review:approve_high_priority", False),
        ("analyst", "runtime:kill_switch", False),
        ("review_board", "review:approve_high_priority", True),
        ("review_board", "run:create", False),
        ("platform_engineer", "runtime:kill_switch", True),
        ("platform_engineer", "review:decide", False),
        ("admin", "anything:at_all", True),
        ("intruder", "opportunity:read", False),
    ],
)
def test_rbac_matrix(app: App, role: str, permission: str, allowed: bool) -> None:
    assert app.platform.policy.check_permission("someone", role, permission).allowed is allowed


def test_kill_switch_halts_model_calls(app: App) -> None:
    ks = app.platform.kill_switch
    ks.set(True, actor="ops", reason="test")
    with pytest.raises(KillSwitchEngaged):
        ks.check()
    prompt = app.pack.prompt("opportunity_explanation")
    with pytest.raises(KillSwitchEngaged):
        app.platform.gateway.invoke(
            capability_id="opportunity.explanation", prompt=prompt, variables={}, output_model=EchoArgs
        )
    ks.set(False, actor="ops", reason="test done")
    ks.check()
