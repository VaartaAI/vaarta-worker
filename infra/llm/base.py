"""
Provider-agnostic LLM interface.

Concrete clients (Groq, Gemini, …) implement complete_json. Quota errors —
per-day, per-key — must surface as LLMQuotaExhausted so the FallbackLLMClient
can switch to the next provider; everything else propagates as-is.
"""
from __future__ import annotations
from abc import ABC, abstractmethod


class LLMQuotaExhausted(Exception):
    """Daily quota for this provider is exhausted; try a different one."""


class LLMClient(ABC):
    name: str  # short identifier used in logs / pool state

    @abstractmethod
    def complete_json(self, system_prompt: str, user_prompt: str, max_tokens: int) -> str:
        """
        Send a chat-style request and return the raw JSON string the model produced.
        Caller does the json.loads.
        """
        raise NotImplementedError
