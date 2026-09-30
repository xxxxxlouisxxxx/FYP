"""HTTP client whose every request passes the policy engine's egress check first."""

from __future__ import annotations

from typing import Any

import httpx

from hop.platform.observability import outbound_trace_headers
from hop.platform.policy_engine import KillSwitch, PolicyEngine


class GovernedHttpClient:
    def __init__(
        self,
        policy: PolicyEngine,
        capability_id: str,
        *,
        kill_switch: KillSwitch | None = None,
        run_id: str | None = None,
        timeout_s: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.policy = policy
        self.capability_id = capability_id
        self.kill_switch = kill_switch
        self.run_id = run_id
        self._client = httpx.Client(timeout=timeout_s, transport=transport, follow_redirects=False)

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self.kill_switch is not None:
            self.kill_switch.check()
        self.policy.enforce_egress(self.capability_id, url, self.run_id)
        headers = {**outbound_trace_headers(), **kwargs.pop("headers", {})}
        return self._client.request(method, url, headers=headers, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def close(self) -> None:
        self._client.close()
