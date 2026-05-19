"""
Provider-agnostic LLM interface.

Concrete clients (Groq, Gemini, …) implement complete_json. Quota errors —
per-day, per-key — must surface as LLMQuotaExhausted so the FallbackLLMClient
can switch to the next provider; everything else propagates as-is.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass


class LLMQuotaExhausted(Exception):
    """Daily quota for this provider is exhausted; try a different one."""


@dataclass
class LLMResponse:
    """
    Raw text from an LLM plus the token count that call actually used.
    `tokens_used == 0` means the provider didn't report usage; callers should
    fall back to a conservative estimate for budget bookkeeping.
    """
    text: str
    tokens_used: int = 0


class LLMClient(ABC):
    name: str  # short identifier used in logs / pool state

    @abstractmethod
    def complete_json(self, system_prompt: str, user_prompt: str, max_tokens: int) -> LLMResponse:
        """
        Send a chat-style request and return the raw JSON string the model
        produced plus the actual tokens used. Caller does json.loads on .text.
        """
        raise NotImplementedError
