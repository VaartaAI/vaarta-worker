"""
Thread-safe daily token budget manager for Groq API.

Groq free tier: ~100k tokens/day. We reserve 10k as buffer, so default budget = 90k.
Resets at UTC midnight (when the date changes).
"""
from __future__ import annotations
import threading
from datetime import date
import structlog

logger = structlog.get_logger(__name__)


class TokenRateLimiter:
    """In-process daily token budget. Not persistent across restarts."""

    def __init__(self, daily_limit: int = 90_000) -> None:
        self._daily_limit = daily_limit
        self._used: int = 0
        self._date: date = date.today()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Internal

    def _reset_if_new_day(self) -> None:
        today = date.today()
        if today != self._date:
            logger.info("token_budget_reset", previous_used=self._used, date=str(today))
            self._used = 0
            self._date = today

    # ------------------------------------------------------------------
    # Public API

    def can_use(self, tokens: int) -> bool:
        """Return True if the budget can absorb `tokens` more."""
        with self._lock:
            self._reset_if_new_day()
            return (self._used + tokens) <= self._daily_limit

    def consume(self, tokens: int) -> bool:
        """
        Deduct `tokens` from the budget.
        Returns True on success, False if the budget would be exceeded.
        """
        with self._lock:
            self._reset_if_new_day()
            if (self._used + tokens) > self._daily_limit:
                logger.warning(
                    "token_budget_exceeded",
                    requested=tokens,
                    used=self._used,
                    limit=self._daily_limit,
                )
                return False
            self._used += tokens
            logger.debug(
                "token_consumed",
                tokens=tokens,
                total_used=self._used,
                remaining=self._daily_limit - self._used,
            )
            return True

    @property
    def remaining(self) -> int:
        with self._lock:
            self._reset_if_new_day()
            return self._daily_limit - self._used

    @property
    def used(self) -> int:
        with self._lock:
            self._reset_if_new_day()
            return self._used
