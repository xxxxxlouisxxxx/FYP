"""Governed tool execution for bounded agents: deny-by-default, validated arguments, step and time limits."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from hop.platform.observability import Telemetry
from hop.platform.policy_engine import PolicyEngine


class MaxStepsExceeded(RuntimeError):
    pass


class AgentTimeout(TimeoutError):
    pass


class ToolArgumentError(ValueError):
    pass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    fn: Callable[[Any], Any]
    args_model: type[BaseModel]
    description: str = ""


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, name: str, fn: Callable[[Any], Any], args_model: type[BaseModel], description: str = "") -> None:
        if name in self._tools:
            raise ValueError(f"tool {name} already registered")
        self._tools[name] = ToolSpec(name, fn, args_model, description)

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)


class AgentSession:
    """One bounded agent invocation, limited by its capability manifest."""

    def __init__(
        self,
        *,
        policy: PolicyEngine,
        tools: ToolRegistry,
        telemetry: Telemetry,
        capability_id: str,
        run_id: str | None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.policy = policy
        self.tools = tools
        self.telemetry = telemetry
        self.capability_id = capability_id
        self.run_id = run_id
        self.manifest = policy.registry.get(capability_id)
        self.steps = 0
        self._clock = clock
        self._started = clock()
        policy.check_capability(capability_id, run_id)

    def call(self, tool: str, **kwargs: Any) -> Any:
        self.steps += 1
        if self.steps > self.manifest.max_steps:
            raise MaxStepsExceeded(f"{self.capability_id} exceeded max_steps={self.manifest.max_steps}")
        if self._clock() - self._started > self.manifest.max_duration_seconds:
            raise AgentTimeout(f"{self.capability_id} exceeded {self.manifest.max_duration_seconds}s")
        self.policy.enforce_tool(self.capability_id, tool, self.run_id)
        spec = self.tools.get(tool)
        if spec is None:
            raise ToolArgumentError(f"tool {tool} is granted but not implemented")
        try:
            args = spec.args_model.model_validate(kwargs)
        except ValidationError as exc:
            raise ToolArgumentError(f"invalid arguments for {tool}: {exc}") from exc
        with self.telemetry.span(
            f"tool.{tool}",
            {
                "capability.id": self.capability_id,
                "capability.version": self.manifest.version,
                "agent.step": self.steps,
            },
        ):
            return spec.fn(args)
