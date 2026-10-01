"""Per-run monetary budget ledger. Spend is reserved before a call and fails closed."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from hop.platform.workflow_runtime.errors import BudgetExceeded


@dataclass
class BudgetLedger:
    limit_usd: float
    spent_usd: float = 0.0
    entries: list[tuple[str, float]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.limit_usd - self.spent_usd)

    def can_spend(self, amount: float) -> bool:
        return self.spent_usd + amount <= self.limit_usd + 1e-12

    def spend(self, amount: float, label: str) -> None:
        if amount < 0:
            raise ValueError("amount must be non-negative")
        with self._lock:
            if not self.can_spend(amount):
                raise BudgetExceeded(
                    f"budget exceeded by {label}: spent ${self.spent_usd:.4f} + ${amount:.4f} > ${self.limit_usd:.4f}"
                )
            self.spent_usd += amount
            self.entries.append((label, amount))
