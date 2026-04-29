"""
Gemini client via the google-genai SDK.

Quota detection is by error-message inspection because the new SDK surfaces
RPD / TPM / TPD failures as a generic APIError with a 429 status — there is
no single dedicated exception class to catch.
"""
from __future__ import annotations

from google import genai
from google.genai import types

from infra.llm.base import LLMClient, LLMQuotaExhausted


_QUOTA_INDICATORS = (
    "quota",
    "exhaust",
    "rate limit",
    "429",
    "resource_exhausted",
    "per day",
    "per minute",
)


class GeminiLLMClient(LLMClient):

    name = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        self._client = genai.Client(api_key=api_key)
        self._model = model

    def complete_json(self, system_prompt: str, user_prompt: str, max_tokens: int) -> str:
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    temperature=0.3,
                    max_output_tokens=max_tokens,
                ),
            )
        except Exception as exc:
            s = str(exc).lower()
            if any(token in s for token in _QUOTA_INDICATORS):
                raise LLMQuotaExhausted(str(exc)) from exc
            raise
        return (response.text or "").strip()
