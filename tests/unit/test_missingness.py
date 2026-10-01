import pytest
from pydantic import ValidationError

from hop.platform.common_contracts import MeasuredValue, Proportion, ValueState, metric_field
from hop.platform.common_contracts.missingness import MISSING_STATES, MissingValueError


def test_missing_value_never_carries_a_number() -> None:
    for state in MISSING_STATES:
        with pytest.raises(ValidationError):
            MeasuredValue(state=state, value=0.0)
        assert MeasuredValue.missing(state, "why").value is None


def test_zero_and_missing_are_distinct() -> None:
    zero = MeasuredValue.observed(0)
    missing = MeasuredValue.missing(ValueState.NOT_COLLECTED, "provider returned null")
    assert zero.state == ValueState.OBSERVED_ZERO and zero.value == 0.0
    assert metric_field(zero) == 0.0
    assert metric_field(missing) is None
    assert missing.display() == "missing (NOT_COLLECTED)"
    with pytest.raises(MissingValueError):
        missing.require()


def test_observed_value_state_rejects_zero() -> None:
    with pytest.raises(ValidationError):
        MeasuredValue(state=ValueState.OBSERVED_VALUE, value=0)


def test_proportion_carries_n_and_ci() -> None:
    p = Proportion.from_counts(2, 10)
    assert p.rate == 0.2 and p.n == 10
    assert p.ci_low is not None and p.ci_high is not None and p.ci_low < 0.2 < p.ci_high
    assert p.exploratory, "n < 30 must be flagged exploratory"
    assert "n=10" in p.display() and "CI" in p.display()
    assert not Proportion.from_counts(20, 40).exploratory


def test_proportion_without_observations_is_insufficient_sample() -> None:
    p = Proportion.from_counts(0, 0)
    assert p.state == ValueState.INSUFFICIENT_SAMPLE
    assert p.rate is None and metric_field(p, "rate") is None


def test_observed_proportion_requires_interval() -> None:
    with pytest.raises(ValidationError):
        Proportion(state=ValueState.OBSERVED_VALUE, successes=1, n=2, rate=0.5)
    with pytest.raises(ValidationError):
        Proportion(state=ValueState.PROVIDER_ERROR, rate=0.0)


def test_metric_round_trip_through_json() -> None:
    p = Proportion.from_counts(3, 12)
    assert Proportion.model_validate_json(p.model_dump_json()) == p
