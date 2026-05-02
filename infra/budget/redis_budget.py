"""
Redis-backed shared TokenBudget.

All worker processes share a single counter per (provider, UTC date). The
date is part of the Redis key, so the counter naturally rolls over at UTC
midnight: tomorrow's reads hit a fresh key starting at 0. Old keys auto-
expire 25 hours after their first write.

INCRBY is atomic, so concurrent consume() calls from many workers never
lose counts.
"""
from __future__ import annotations
from datetime import datetime, timezone

import structlog
import redis

from infra.budget.base import TokenBudget
from infra import metrics as m

logger = structlog.get_logger(__name__)

# 25h: comfortably past UTC midnight rollover so we never wipe today's count
# during the brief window when both keys (yesterday's expiring + today's
# being created) are visible.
_KEY_TTL_SECONDS = 25 * 3600


class RedisTokenBudget(TokenBudget):
    """Daily budget in Redis. Shared across all worker processes/replicas."""

    def __init__(self, client: redis.Redis, provider: str, daily_limit: int) -> None:
        self._client = client
        self._provider = provider
        self._daily_limit = daily_limit

    def _key(self) -> str:
        today = datetime.now(timezone.utc).date().isoformat()
        return f"budget:{self._provider}:{today}"

    def can_use(self, tokens: int) -> bool:
        used = int(self._client.get(self._key()) or 0)
        return (used + tokens) <= self._daily_limit

    def consume(self, tokens: int) -> None:
        key = self._key()
        # Pipeline so INCRBY and EXPIRE travel in a single round-trip.
        # EXPIRE NX = "only set TTL if no TTL is set yet" — otherwise every
        # consume call would push the expiry forward and old days would never
        # get cleaned up.
        pipe = self._client.pipeline()
        pipe.incrby(key, tokens)
        pipe.expire(key, _KEY_TTL_SECONDS, nx=True)
        results = pipe.execute()
        new_total = int(results[0])
        if new_total > self._daily_limit:
            logger.warning(
                "budget_overrun",
                provider=self._provider,
                used=new_total,
                limit=self._daily_limit,
            )
            m.budget_overrun_total.add(1, {"provider": self._provider})

    @property
    def remaining(self) -> int:
        used = int(self._client.get(self._key()) or 0)
        return max(0, self._daily_limit - used)
