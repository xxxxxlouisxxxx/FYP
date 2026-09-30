"""OpenAI-compatible chat-completions adapter. Only used when ``OPENAI_API_KEY`` is set.

Requests go through ``GovernedHttpClient`` so the invoking capability's egress allowlist applies.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from hop.platform.integrations.http import GovernedHttpClient
from hop.platform.model_gateway import (
    ModelCall,
    ModelPermanentError,
    ModelTransientError,
    RawCompletion,
)
from hop.platform.policy_engine import KillSwitch, PolicyEngine


class OpenAICompatibleAdapter:
    provider = "openai_compatible"

    def __init__(
        self,
        *,
        policy: PolicyEngine,
        kill_switch: KillSwitch,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        remote_model: str | None = None,
    ) -> None:
        self.policy = policy
        self.kill_switch = kill_switch
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.remote_model = remote_model
        self.host = urlsplit(self.base_url).hostname

    def complete(self, call: ModelCall) -> RawCompletion:
        client = GovernedHttpClient(
            self.policy, call.capability_id, kill_switch=self.kill_switch, run_id=call.run_id, timeout_s=call.timeout_s
        )
        try:
            response = client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self.remote_model or call.model_id,
                    "messages": call.messages,
                    "max_tokens": call.max_output_tokens,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                },
            )
        finally:
            client.close()
        if response.status_code in (408, 409, 429) or response.status_code >= 500:
            raise ModelTransientError(f"model provider returned {response.status_code}")
        if response.status_code >= 400:
            raise ModelPermanentError(f"model provider returned {response.status_code}")
        body = response.json()
        usage = body.get("usage", {})
        return RawCompletion(
            text=body["choices"][0]["message"]["content"],
            tokens_in=int(usage.get("prompt_tokens", 0)),
            tokens_out=int(usage.get("completion_tokens", 0)),
            provider_request_id=body.get("id"),
        )
