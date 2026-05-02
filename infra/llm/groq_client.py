from __future__ import annotations
from groq import Groq, RateLimitError

from infra.llm.base import LLMClient, LLMQuotaExhausted, LLMResponse


class GroqLLMClient(LLMClient):

    name = "groq"

    def __init__(self, api_key: str, model: str):
        self._client = Groq(api_key=api_key)
        self._model = model

    def complete_json(self, system_prompt: str, user_prompt: str, max_tokens: int) -> LLMResponse:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
        except RateLimitError as exc:
            s = str(exc).lower()
            if "tokens per day" in s or "tpd" in s or "requests per day" in s:
                raise LLMQuotaExhausted(str(exc)) from exc
            raise

        text = (response.choices[0].message.content or "").strip()
        tokens = getattr(getattr(response, "usage", None), "total_tokens", 0) or 0
        return LLMResponse(text=text, tokens_used=int(tokens))
