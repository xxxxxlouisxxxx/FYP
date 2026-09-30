"""Deterministic statistics. No model judgement is ever used for these calculations."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from statistics import NormalDist


def z_for_confidence(confidence: float) -> float:
    if not 0 < confidence < 1:
        raise ValueError("confidence must be in (0, 1)")
    return NormalDist().inv_cdf(1 - (1 - confidence) / 2)


def wilson_interval(successes: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if n <= 0:
        raise ValueError("n must be positive")
    if not 0 <= successes <= n:
        raise ValueError("successes must be within [0, n]")
    z = z_for_confidence(confidence)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    low = max(0.0, centre - margin)
    high = min(1.0, centre + margin)
    if successes == 0:
        low = 0.0
    if successes == n:
        high = 1.0
    return round(low, 6), round(high, 6)


def hhi(counts: Mapping[str, float] | Iterable[float]) -> float:
    """Herfindahl-Hirschman index on the 0-1 scale (1 = monopoly)."""
    values = list(counts.values()) if isinstance(counts, Mapping) else list(counts)
    if any(v < 0 for v in values):
        raise ValueError("counts must be non-negative")
    total = sum(values)
    if total <= 0:
        raise ValueError("HHI undefined for empty distribution")
    return round(sum((v / total) ** 2 for v in values), 6)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))
