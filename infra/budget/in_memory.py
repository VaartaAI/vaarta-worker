"""
In-process daily token budget. Fine for single-worker development; useless
across multiple workers because each process has its own counter.

For production with multiple LLM workers, use RedisTokenBudget.
"""
from __future__ import annotations
import threading
from datetime import date

import structlog

from infra.budget.base import TokenBudget
from infra import metrics as m

logger = structlog.get_logger(__name__)


class InMemoryTokenBudget(TokenBudget):
    """Daily budget held in process memory. Resets when date() changes."""

    def __init__(self, daily_limit: int = 90_000) -> None:
        self._daily_limit = daily_limit
        self._used: int = 0
        self._date: date = date.today()
        self._lock = threading.Lock()

    def _reset_if_new_day(self) -> None:
        today = date.today()
        if today != self._date:
            logger.info("budget_reset", previous_used=self._used, date=str(today))
            self._used = 0
            self._date = today

    def can_use(self, tokens: int) -> bool:
        with self._lock:
            self._reset_if_new_day()
            return (self._used + tokens) <= self._daily_limit

    def consume(self, tokens: int) -> None:
        with self._lock:
            self._reset_if_new_day()
            self._used += tokens
            if self._used > self._daily_limit:
                logger.warning(
                    "budget_overrun",
                    used=self._used,
                    limit=self._daily_limit,
                )
                m.budget_overrun_total.add(1, {"provider": "in-memory"})

    @property
    def remaining(self) -> int:
        with self._lock:
            self._reset_if_new_day()
            return max(0, self._daily_limit - self._used)
