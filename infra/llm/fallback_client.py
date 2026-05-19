"""
Multi-provider LLM client.

Tries providers in the order they're given. Each has its own TokenBudget
(in-memory or Redis-shared) and an "exhausted today" flag flipped when the
provider itself signals daily quota exhaustion via LLMQuotaExhausted.

Construct with the cheapest / preferred provider first.
"""
from __future__ import annotations
import threading
import time
from dataclasses import dataclass

import structlog

from infra.llm.base import LLMClient, LLMQuotaExhausted, LLMResponse
from infra.budget import TokenBudget
from infra import metrics as m

logger = structlog.get_logger(__name__)


@dataclass
class ProviderState:
    client: LLMClient
    limiter: TokenBudget
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

    def complete_json(self, system_prompt: str, user_prompt: str, max_tokens: int) -> LLMResponse:
        last_exc: Exception | None = None

        for provider in self._providers:
            with self._lock:
                if not self._available_locked(provider):
                    continue

            started = time.monotonic()
            try:
                result = provider.client.complete_json(system_prompt, user_prompt, max_tokens)
            except LLMQuotaExhausted as exc:
                logger.warning(
                    "provider_exhausted",
                    provider=provider.client.name,
                    error=str(exc),
                )
                m.provider_exhausted_total.add(1, {"provider": provider.client.name})
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

            elapsed = time.monotonic() - started
            m.llm_latency_seconds.record(elapsed, {"provider": provider.client.name})

            # Use the provider's reported token count when available; fall back
            # to the conservative estimate if usage wasn't surfaced.
            tokens = result.tokens_used if result.tokens_used > 0 else self._tokens_per_call
            m.summary_tokens_used.record(tokens, {"provider": provider.client.name})
            m.provider_used_total.add(1, {"provider": provider.client.name})

            with self._lock:
                provider.limiter.consume(tokens)
            logger.debug(
                "provider_used",
                provider=provider.client.name,
                tokens=tokens,
                estimated=result.tokens_used == 0,
            )
            return result

        if last_exc is not None:
            raise last_exc
        raise LLMQuotaExhausted("all providers exhausted for today")
