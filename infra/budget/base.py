"""
TokenBudget interface — daily token budget for an LLM provider.

Concrete implementations live alongside this module:
    - InMemoryTokenBudget: per-process, fine for single-worker dev.
    - RedisTokenBudget:    shared across workers, the production choice.

Workers depend on this interface, not the concrete impl, so swapping is a
one-line change in the composition root.
"""
from __future__ import annotations
from abc import ABC, abstractmethod


class TokenBudget(ABC):
    """Daily token budget with atomic consumption semantics."""

    @abstractmethod
    def can_use(self, tokens: int) -> bool:
        """
        Pre-flight check: would consuming `tokens` fit within today's budget?
        Advisory only — not synchronized with consume(). The decisive guard
        is consume() itself, but call this first to avoid wasted LLM calls.
        """
        raise NotImplementedError

    @abstractmethod
    def consume(self, tokens: int) -> None:
        """
        Record `tokens` as consumed. Must be atomic with respect to other
        concurrent consumers (locks for in-memory, INCRBY for Redis, etc.).
        Always records — even if the consumption pushes us past the limit —
        because the LLM call has already happened and the bookkeeping must
        not under-count.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def remaining(self) -> int:
        """Tokens remaining in today's budget (clamped to >= 0)."""
        raise NotImplementedError
