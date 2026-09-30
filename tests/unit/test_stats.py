import pytest

from hop.platform.analytics.stats import hhi, wilson_interval


def test_wilson_matches_reference_values() -> None:
    assert wilson_interval(5, 10) == pytest.approx((0.236593, 0.763407), abs=1e-6)
    assert wilson_interval(81, 263) == pytest.approx((0.255289, 0.366210), abs=1e-6)


def test_wilson_boundaries_are_exact() -> None:
    low, high = wilson_interval(0, 7)
    assert low == 0.0 and 0 < high < 1
    low, high = wilson_interval(7, 7)
    assert high == 1.0 and 0 < low < 1


def test_wilson_interval_narrows_with_sample_size() -> None:
    small = wilson_interval(3, 10)
    large = wilson_interval(300, 1000)
    assert (large[1] - large[0]) < (small[1] - small[0])


@pytest.mark.parametrize(("successes", "n"), [(0, 0), (-1, 5), (6, 5)])
def test_wilson_rejects_invalid_input(successes: int, n: int) -> None:
    with pytest.raises(ValueError):
        wilson_interval(successes, n)


def test_hhi() -> None:
    assert hhi({"a": 10}) == 1.0
    assert hhi([1, 1, 1, 1]) == 0.25
    assert hhi({"a": 3, "b": 1}) == pytest.approx(0.625)
    with pytest.raises(ValueError):
        hhi([])
    with pytest.raises(ValueError):
        hhi([1, -1])
