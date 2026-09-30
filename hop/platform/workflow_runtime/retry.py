"""Retry policy with exponential backoff and full jitter."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from hop.platform.workflow_runtime.errors import is_retryable

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_s: float = 0.2
    max_delay_s: float = 5.0
    jitter: bool = True

    def delay(self, attempt: int, rng: random.Random | None = None) -> float:
        """Delay before retry number ``attempt`` (1-based)."""
        cap = min(self.max_delay_s, self.base_delay_s * (2 ** (attempt - 1)))
        if not self.jitter:
            return cap
        return (rng or random).uniform(0, cap)


NO_RETRY = RetryPolicy(max_attempts=1)


@dataclass
class RetryOutcome:
    attempts: int = 0
    retries: int = 0


def retry_call(
    fn: Callable[[], T],
    policy: RetryPolicy,
    *,
    sleep: Callable[[float], None] = time.sleep,
    on_retry: Callable[[int, BaseException, float], None] | None = None,
    outcome: RetryOutcome | None = None,
) -> T:
    attempt = 0
    while True:
        attempt += 1
        if outcome is not None:
            outcome.attempts = attempt
            outcome.retries = attempt - 1
        try:
            return fn()
        except Exception as exc:
            if attempt >= policy.max_attempts or not is_retryable(exc):
                raise
            delay = policy.delay(attempt)
            if on_retry:
                on_retry(attempt, exc, delay)
            sleep(delay)
