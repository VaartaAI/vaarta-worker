"""
Multi-provider LLM client.

Tries providers in the order they're given. Each has its own in-memory
TokenRateLimiter and an "exhausted today" flag flipped when the provider
itself signals daily quota exhaustion via LLMQuotaExhausted.

Construct with the cheapest / preferred provider first.
"""
from __future__ import annotations
import threading
from dataclasses import dataclass

import structlog

from infra.llm.base import LLMClient, LLMQuotaExhausted
from infra.rate_limiter import TokenRateLimiter

logger = structlog.get_logger(__name__)


@dataclass
class ProviderState:
    client: LLMClient
    limiter: TokenRateLimiter
    exhausted_today: bool = False


class FallbackLLMClient(LLMClient):

    name = "fallback"

    def __init__(self, providers: list[ProviderState], tokens_per_call: int = 1500):
        if not providers:
            raise ValueError("FallbackLLMClient needs at least one provider")
        self._providers = providers
        self._tokens_per_call = tokens_per_call
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Pre-flight + introspection (used by the LLM worker loop)

    def has_capacity(self) -> bool:
        with self._lock:
            return any(self._available_locked(p) for p in self._providers)

    def status(self) -> dict[str, int]:
        """Per-provider remaining tokens; -1 means exhausted_today flag is set."""
        with self._lock:
            return {
                p.client.name: -1 if p.exhausted_today else p.limiter.remaining
                for p in self._providers
            }

    def _available_locked(self, p: ProviderState) -> bool:
        return (not p.exhausted_today) and p.limiter.can_use(self._tokens_per_call)

    # ------------------------------------------------------------------
    # The actual call

    def complete_json(self, system_prompt: str, user_prompt: str, max_tokens: int) -> str:
        last_exc: Exception | None = None

        for provider in self._providers:
            with self._lock:
                if not self._available_locked(provider):
                    continue

            try:
                result = provider.client.complete_json(system_prompt, user_prompt, max_tokens)
            except LLMQuotaExhausted as exc:
                logger.warning(
                    "provider_exhausted",
                    provider=provider.client.name,
                    error=str(exc),
                )
                with self._lock:
                    provider.exhausted_today = True
                continue
            except Exception as exc:
                # Transient (network blip, 5xx, parse error). Try the next provider
                # rather than failing the whole call.
                logger.warning(
                    "provider_call_failed",
                    provider=provider.client.name,
                    error=str(exc),
                )
                last_exc = exc
                continue

            with self._lock:
                provider.limiter.consume(self._tokens_per_call)
            logger.debug("provider_used", provider=provider.client.name)
            return result

        if last_exc is not None:
            raise last_exc
        raise LLMQuotaExhausted("all providers exhausted for today")
