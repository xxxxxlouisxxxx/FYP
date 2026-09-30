"""Failure classification used by retries, dead-lettering and alerting."""

from __future__ import annotations


class TransientError(RuntimeError):
    """Retryable (provider 5xx, timeouts, rate limits)."""

    failure_class = "transient"


class PermanentError(RuntimeError):
    """Not retryable (bad request, contract violation)."""

    failure_class = "permanent"


class BudgetExceeded(RuntimeError):
    failure_class = "budget_exceeded"


class ActivityTimeout(TransientError):
    failure_class = "timeout"


class RunCancelled(RuntimeError):
    failure_class = "cancelled"


def classify(exc: BaseException) -> str:
    from hop.platform.policy_engine import KillSwitchEngaged, PolicyViolation

    if isinstance(exc, KillSwitchEngaged):
        return "kill_switch"
    if isinstance(exc, PolicyViolation):
        return "policy_violation"
    known = getattr(exc, "failure_class", None)
    if known:
        return str(known)
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, ValueError):
        return "validation"
    return "unexpected"


def is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, TransientError | TimeoutError) and classify(exc) not in {"kill_switch", "policy_violation"}
