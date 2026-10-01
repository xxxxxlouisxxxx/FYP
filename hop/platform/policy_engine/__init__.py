"""Deterministic policy enforcement: tool access, egress, models, RBAC, budgets and the kill switch."""

from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select

from hop.platform.audit import AuditLog
from hop.platform.capability_registry import CapabilityRegistry, UnknownCapabilityError
from hop.platform.common_contracts import ActorType, PolicyDecision
from hop.platform.observability import current_trace_id
from hop.platform.storage.db import PolicyDecisionRow, SettingRow, Store

POLICY_VERSION = "policy-v1.0.0"
KILL_SWITCH_KEY = "runtime.kill_switch"


class PolicyViolation(PermissionError):
    def __init__(self, decision: PolicyDecision) -> None:
        super().__init__(f"{decision.action} denied for {decision.subject} on {decision.resource}: {decision.reason}")
        self.decision = decision


class KillSwitchEngaged(RuntimeError):
    pass


# Role-based access (placeholder for Entra ID group mapping) ---------------------------------
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "viewer": {"opportunity:read", "run:read", "trace:read"},
    "analyst": {
        "opportunity:read",
        "run:read",
        "trace:read",
        "evidence:read",
        "evidence:raw_read",
        "run:create",
        "review:submit",
        "review:decide",
        "evaluation:run",
        "gap_matrix:tune",
    },
    "domain_reviewer": {
        "opportunity:read",
        "run:read",
        "trace:read",
        "evidence:read",
        "evidence:raw_read",
        "review:submit",
        "review:decide",
        "gap_matrix:tune",
    },
    "review_board": {
        "opportunity:read",
        "run:read",
        "trace:read",
        "evidence:read",
        "evidence:raw_read",
        "review:submit",
        "review:decide",
        "review:approve_high_priority",
        "gap_matrix:tune",
    },
    "platform_engineer": {
        "opportunity:read",
        "run:read",
        "trace:read",
        "evidence:read",
        "run:create",
        "runtime:kill_switch",
        "capability:revoke",
        "evaluation:run",
        "config:write",
    },
    "admin": {"*"},
}


class KillSwitch:
    def __init__(self, store: Store, env_engaged: bool = False) -> None:
        self.store = store
        self.env_engaged = env_engaged

    def engaged(self) -> bool:
        if self.env_engaged:
            return True
        with self.store.session() as s:
            row = s.get(SettingRow, KILL_SWITCH_KEY)
            return bool(row and row.value.get("engaged"))

    def set(self, engaged: bool, *, actor: str, reason: str) -> None:
        with self.store.session() as s:
            s.merge(SettingRow(key=KILL_SWITCH_KEY, value={"engaged": engaged, "actor": actor, "reason": reason}))

    def check(self) -> None:
        if self.engaged():
            raise KillSwitchEngaged("emergency kill switch is engaged; all agent and provider calls are halted")


class PolicyEngine:
    def __init__(
        self,
        registry: CapabilityRegistry,
        store: Store,
        audit: AuditLog,
        *,
        env: str = "sandbox",
        global_model_allowlist: set[str] | None = None,
    ) -> None:
        self.registry = registry
        self.store = store
        self.audit = audit
        self.env = env
        self.global_model_allowlist = global_model_allowlist or set()

    # decisions ----------------------------------------------------------------------------
    def _decide(
        self, subject: str, action: str, resource: str, allowed: bool, reason: str, run_id: str | None
    ) -> PolicyDecision:
        decision = PolicyDecision(
            subject=subject,
            action=action,
            resource=resource,
            allowed=allowed,
            reason=reason,
            policy_version=POLICY_VERSION,
            run_id=run_id,
            trace_id=current_trace_id(),
        )
        with self.store.session() as s:
            s.add(
                PolicyDecisionRow(
                    decision_id=decision.decision_id,
                    run_id=run_id,
                    allowed=int(allowed),
                    action=action,
                    body=decision.model_dump(mode="json"),
                )
            )
        if not allowed:
            self.audit.record(
                actor=subject,
                actor_type=ActorType.AGENT,
                action=f"policy.{action}.denied",
                resource_type="policy",
                resource_id=resource,
                outcome="DENIED",
                details={"reason": reason, "policy_version": POLICY_VERSION, "run_id": run_id},
                trace_id=decision.trace_id,
            )
        return decision

    def _enforce(self, decision: PolicyDecision) -> PolicyDecision:
        if not decision.allowed:
            raise PolicyViolation(decision)
        return decision

    def check_capability(self, capability_id: str, run_id: str | None = None) -> PolicyDecision:
        ok, reason = self.registry.executable_status(capability_id, self.env)
        return self._decide(capability_id, "capability.execute", capability_id, ok, reason, run_id)

    def enforce_capability(self, capability_id: str, run_id: str | None = None) -> PolicyDecision:
        return self._enforce(self.check_capability(capability_id, run_id))

    def check_tool(self, capability_id: str, tool: str, run_id: str | None = None) -> PolicyDecision:
        ok, reason = self.registry.executable_status(capability_id, self.env)
        if ok:
            manifest = self.registry.get(capability_id)
            if tool in manifest.allowed_tools:
                reason = "tool granted by capability manifest"
            else:
                ok, reason = False, "tool not in manifest allowed_tools (deny-by-default)"
        return self._decide(capability_id, "tool.invoke", tool, ok, reason, run_id)

    def enforce_tool(self, capability_id: str, tool: str, run_id: str | None = None) -> PolicyDecision:
        return self._enforce(self.check_tool(capability_id, tool, run_id))

    def check_egress(self, capability_id: str, url: str, run_id: str | None = None) -> PolicyDecision:
        ok, reason = self._egress_reason(capability_id, url)
        return self._decide(capability_id, "network.egress", url[:300], ok, reason, run_id)

    def enforce_egress(self, capability_id: str, url: str, run_id: str | None = None) -> PolicyDecision:
        return self._enforce(self.check_egress(capability_id, url, run_id))

    def _egress_reason(self, capability_id: str, url: str) -> tuple[bool, str]:
        ok, reason = self.registry.executable_status(capability_id, self.env)
        if not ok:
            return False, reason
        try:
            parts = urlsplit(url)
        except ValueError:
            return False, "malformed URL"
        if parts.scheme != "https":
            return False, "only https egress is permitted"
        host = (parts.hostname or "").lower().rstrip(".")
        if not host:
            return False, "missing host"
        if parts.username or parts.password:
            return False, "credentials in URL are not permitted"
        if parts.port not in (None, 443):
            return False, "non-standard port"
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            ip = None
        if ip is not None:
            return False, "IP-literal egress blocked (SSRF protection)"
        if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
            return False, "internal hostname blocked (SSRF protection)"
        allowlist = [h.lower() for h in self.registry.get(capability_id).network_policy.outbound_allowlist]
        if host in allowlist:
            return True, "host in capability egress allowlist"
        return False, f"host {host} not in capability egress allowlist {allowlist or '[none]'}"

    def check_model(self, capability_id: str, model_id: str, run_id: str | None = None) -> PolicyDecision:
        ok, reason = self.registry.executable_status(capability_id, self.env)
        if ok:
            manifest = self.registry.get(capability_id)
            allowed = set(manifest.model_policy.allowed_models if manifest.model_policy else [])
            if model_id not in self.global_model_allowlist:
                ok, reason = False, "model not on gateway allowlist"
            elif model_id not in allowed:
                ok, reason = False, "model not permitted by capability model policy"
            else:
                reason = "model allowed"
        return self._decide(capability_id, "model.invoke", model_id, ok, reason, run_id)

    def check_budget(
        self, capability_id: str, requested_usd: float, remaining_usd: float, run_id: str | None = None
    ) -> PolicyDecision:
        try:
            cap_limit = self.registry.get(capability_id).max_cost_usd
        except UnknownCapabilityError:
            cap_limit = 0.0
        ok = requested_usd <= remaining_usd + 1e-12 and requested_usd <= cap_limit + 1e-12
        reason = (
            "within budget"
            if ok
            else f"requested ${requested_usd:.4f} exceeds remaining run budget ${remaining_usd:.4f} "
            f"or capability limit ${cap_limit:.4f}"
        )
        return self._decide(capability_id, "budget.spend", f"{requested_usd:.6f}", ok, reason, run_id)

    # RBAC ---------------------------------------------------------------------------------
    def check_permission(self, user: str, role: str, permission: str, resource: str = "*") -> PolicyDecision:
        granted = ROLE_PERMISSIONS.get(role, set())
        ok = "*" in granted or permission in granted
        reason = f"role {role} {'grants' if ok else 'does not grant'} {permission}"
        return self._decide(f"user:{user}", f"rbac.{permission}", resource, ok, reason, None)

    def enforce_permission(self, user: str, role: str, permission: str, resource: str = "*") -> PolicyDecision:
        return self._enforce(self.check_permission(user, role, permission, resource))

    # reporting ----------------------------------------------------------------------------
    def decisions(self, *, allowed: bool | None = None, limit: int = 500) -> list[PolicyDecision]:
        with self.store.session() as s:
            q = select(PolicyDecisionRow).order_by(PolicyDecisionRow.created_at.desc()).limit(limit)
            if allowed is not None:
                q = q.where(PolicyDecisionRow.allowed == int(allowed))
            return [PolicyDecision.model_validate(r.body) for r in s.execute(q).scalars()]


def summarize_decisions(decisions: list[PolicyDecision]) -> dict[str, Any]:
    denied = [d for d in decisions if not d.allowed]
    return {"total": len(decisions), "denied": len(denied), "allowed": len(decisions) - len(denied)}
