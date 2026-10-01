"""Explicit missing-data semantics (spec section 8.4).

Missing, unavailable, blocked and genuinely zero are different states. Nothing in the platform may
convert a missing value into zero: missing values carry ``value=None`` and a non-observed state.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from hop.platform.analytics.stats import wilson_interval
from hop.platform.common_contracts.base import Contract


class ValueState(StrEnum):
    OBSERVED_ZERO = "OBSERVED_ZERO"
    OBSERVED_VALUE = "OBSERVED_VALUE"
    NOT_COLLECTED = "NOT_COLLECTED"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    PARSING_FAILED = "PARSING_FAILED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    SUPPRESSED_BY_POLICY = "SUPPRESSED_BY_POLICY"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"


OBSERVED_STATES = frozenset({ValueState.OBSERVED_ZERO, ValueState.OBSERVED_VALUE})
MISSING_STATES = frozenset(set(ValueState) - OBSERVED_STATES)


class MissingValueError(ValueError):
    """Raised when code tries to use a missing value as if it were observed."""


class MeasuredValue(Contract):
    kind: Literal["measured"] = "measured"
    state: ValueState
    value: float | None = None
    n: int | None = Field(default=None, ge=0, description="Number of underlying observations")
    unit: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _check_state(self) -> MeasuredValue:
        if self.state == ValueState.OBSERVED_VALUE:
            if self.value is None:
                raise ValueError("OBSERVED_VALUE requires a value")
            if self.value == 0:
                raise ValueError("a genuine zero must use OBSERVED_ZERO")
        elif self.state == ValueState.OBSERVED_ZERO:
            if self.value is None:
                self.value = 0.0
            elif self.value != 0:
                raise ValueError("OBSERVED_ZERO requires value == 0")
        elif self.value is not None:
            raise ValueError(f"{self.state} must not carry a value (missing is never coerced)")
        return self

    @property
    def is_observed(self) -> bool:
        return self.state in OBSERVED_STATES

    @classmethod
    def observed(cls, value: float, n: int | None = None, unit: str | None = None) -> MeasuredValue:
        state = ValueState.OBSERVED_ZERO if value == 0 else ValueState.OBSERVED_VALUE
        return cls(state=state, value=float(value), n=n, unit=unit)

    @classmethod
    def missing(cls, state: ValueState, reason: str, n: int | None = None) -> MeasuredValue:
        if state in OBSERVED_STATES:
            raise ValueError("missing() requires a non-observed state")
        return cls(state=state, reason=reason, n=n)

    def require(self) -> float:
        if not self.is_observed or self.value is None:
            raise MissingValueError(f"value is {self.state}: {self.reason or ''}")
        return self.value

    def display(self, fmt: str = "{:.2f}") -> str:
        if not self.is_observed:
            return f"missing ({self.state})"
        text = fmt.format(self.value)
        return f"{text} (n={self.n})" if self.n is not None else text


class Proportion(Contract):
    """A rate that always travels with its sample size and Wilson interval."""

    kind: Literal["proportion"] = "proportion"
    state: ValueState
    successes: int | None = Field(default=None, ge=0)
    n: int | None = Field(default=None, ge=0)
    rate: float | None = Field(default=None, ge=0, le=1)
    ci_low: float | None = Field(default=None, ge=0, le=1)
    ci_high: float | None = Field(default=None, ge=0, le=1)
    confidence: float = 0.95
    method: Literal["wilson"] = "wilson"
    exploratory: bool = False
    reason: str | None = None

    @model_validator(mode="after")
    def _check(self) -> Proportion:
        if self.state in OBSERVED_STATES:
            if self.n is None or self.successes is None or self.rate is None:
                raise ValueError("observed proportion requires successes, n and rate")
            if self.ci_low is None or self.ci_high is None:
                raise ValueError("observed proportion requires a confidence interval")
            if self.successes > self.n:
                raise ValueError("successes cannot exceed n")
        elif self.rate is not None:
            raise ValueError(f"{self.state} must not carry a rate")
        return self

    @property
    def is_observed(self) -> bool:
        return self.state in OBSERVED_STATES

    @classmethod
    def from_counts(
        cls, successes: int, n: int, *, confidence: float = 0.95, exploratory_below: int = 30
    ) -> Proportion:
        if n <= 0:
            return cls(state=ValueState.INSUFFICIENT_SAMPLE, n=0, successes=0, reason="no observations")
        low, high = wilson_interval(successes, n, confidence)
        state = ValueState.OBSERVED_ZERO if successes == 0 else ValueState.OBSERVED_VALUE
        return cls(
            state=state,
            successes=successes,
            n=n,
            rate=successes / n,
            ci_low=low,
            ci_high=high,
            confidence=confidence,
            exploratory=n < exploratory_below,
        )

    @classmethod
    def missing(cls, state: ValueState, reason: str) -> Proportion:
        if state in OBSERVED_STATES:
            raise ValueError("missing() requires a non-observed state")
        return cls(state=state, reason=reason)

    def field(self, name: str) -> float | None:
        if not self.is_observed:
            return None
        return {"rate": self.rate, "ci_low": self.ci_low, "ci_high": self.ci_high, "value": self.rate}.get(name)

    def display(self) -> str:
        if not self.is_observed:
            return f"missing ({self.state})"
        tag = " exploratory" if self.exploratory else ""
        return (
            f"{self.rate:.1%} (n={self.n}, {int(self.confidence * 100)}% CI {self.ci_low:.1%}-{self.ci_high:.1%}){tag}"
        )


MetricValue = Annotated[MeasuredValue | Proportion, Field(discriminator="kind")]


def metric_field(metric: MeasuredValue | Proportion | None, field: str = "value") -> float | None:
    """Read a numeric field; returns None (never 0) for missing metrics."""
    if metric is None or not metric.is_observed:
        return None
    if isinstance(metric, Proportion):
        return metric.field(field)
    return metric.value
