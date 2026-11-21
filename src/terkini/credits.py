"""Credit guard (PRD §3 P0.11, D11): refuse a Tavily call that could cross the per-run or per-day limit.

The guard checks the worst-case cost before each call and records the credits the response reports afterwards (D-010).
A refused call raises CreditLimitReached; the checker stops cleanly and reports which claims were not checked.
"""

from __future__ import annotations

import math
import threading
from datetime import date

from terkini.budget import TavilyBudget
from terkini.cache import Cache


class CreditLimitReached(RuntimeError):
    pass


class CreditGuard:
    def __init__(self, budget: TavilyBudget, ledger: Cache, today: date):
        self.budget = budget
        self._ledger = ledger
        self._today = today
        self.spent_this_run = 0
        self._lock = threading.Lock()  # the eval shares one guard between worker threads

    @property
    def spent_today(self) -> int:
        return self._ledger.spent_on(self._today)

    def search_cost(self, depth: str) -> int:
        c = self.budget.costs
        return c.search_advanced if depth == "advanced" else c.search_basic

    def extract_cost(self, n_urls: int) -> int:
        return math.ceil(n_urls / self.budget.costs.extract_urls_per_credit)

    def allow(self, cost: int) -> None:
        """Raise before a call whose cost would cross a limit."""
        with self._lock:
            self._allow(cost)

    def _allow(self, cost: int) -> None:
        limits = self.budget.limits
        if self.spent_this_run + cost > limits.per_run:
            raise CreditLimitReached(
                f"run limit: {self.spent_this_run} of {limits.per_run} credits used, next call needs {cost}"
            )
        if self.spent_today + cost > limits.per_day:
            raise CreditLimitReached(
                f"daily limit: {self.spent_today} of {limits.per_day} credits used today, next call needs {cost}"
            )

    def record(self, credits: int) -> None:
        if credits <= 0:
            return
        with self._lock:
            self.spent_this_run += credits
        self._ledger.add_spent(self._today, credits)
