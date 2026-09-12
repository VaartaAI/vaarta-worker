from __future__ import annotations
import re
import time
from collections import deque

import structlog
from google import genai
from google.genai import types

from infra.embeddings.base import EmbeddingClient, EmbeddingError, EmbeddingQuotaExhausted

logger = structlog.get_logger(__name__)

_RETRY_DELAY = re.compile(r"retry(?:Delay|.in)['\"]?\s*:?\s*['\"]?([0-9.]+)\s*s", re.I)
_CLIENT_ERROR = re.compile(r"\b(400|401|403|404|INVALID_ARGUMENT|PERMISSION_DENIED|NOT_FOUND)\b")
_QUOTA_FIELD = re.compile(r"(quotaId|quotaMetric|quotaValue)['\"]?\s*:\s*['\"]?([^'\",}]+)")


def _quota_details(msg: str) -> dict:
    """Pull quotaId / quotaMetric / quotaValue out of a Google 429 message for the log."""
    return {k: v.strip() for k, v in _QUOTA_FIELD.findall(msg)}
_MAX_ATTEMPTS = 4


class GeminiEmbeddingClient(EmbeddingClient):
    """
    gemini-embedding-001 via the google-genai SDK.

    Free-tier quotas (metric embed_content_free_tier_requests): 100 per
    minute AND a per-day cap (quotaId ...PerDayPerUserPerProjectPerModel,
    1000/day observed 2026-09-12; resets at midnight Pacific). EVERY text in a
    batch counts as one request — including texts in a batch that was
    rejected with 429. A per-day 429 therefore raises EmbeddingQuotaExhausted
    immediately and the client refuses further calls for the rest of the
    process; retrying would only burn tomorrow's quota. So batching only saves HTTP round
    trips, not quota, and a 100-text batch retried after the server's
    suggested ~50 s delay collides with its own rejected predecessor forever
    (observed 2026-09-12). Hence: batches of 40 % of the per-minute budget, a
    sliding 60 s pacer that counts attempts (not just successes), and on 429 a
    wait of at least one full window.

    Rate limits are per model per project, so this does not draw from the
    summarization model's quota. It is deliberately NOT registered in the
    LLM fallback chain or its daily token budget.
    """

    name = "gemini"

    def __init__(self, api_key: str, model: str, dimensions: int,
                 per_minute: int = 100, max_wait_seconds: float = 240.0,
                 request_timeout_seconds: float = 30.0):
        # Hard HTTP timeout: without it a stalled connection blocks ingest
        # indefinitely (observed 2026-09-12). Value is milliseconds.
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=int(request_timeout_seconds * 1000)),
        )
        self._model = model
        self.dimensions = dimensions
        self._per_minute = max(1, per_minute)
        self._max_wait = max_wait_seconds
        self._sent: deque[tuple[float, int]] = deque()  # (timestamp, texts) attempted in the last 60 s
        self._batch = max(1, min(self._per_minute, (self._per_minute * 2) // 5))  # 40 at the default 100
        self._daily_exhausted = False

    # ── public ────────────────────────────────────────────────────────────
    def embed(self, texts: list[str]) -> list[list[float]]:
        if self._daily_exhausted:
            raise EmbeddingQuotaExhausted("daily embedding quota exhausted earlier in this run")
        out: list[list[float]] = []
        deadline = time.monotonic() + self._max_wait
        for i in range(0, len(texts), self._batch):
            chunk = texts[i:i + self._batch]
            self._wait_for_capacity(len(chunk), deadline)
            out.extend(self._embed_batch(chunk, deadline))
        return out

    # ── pacing ────────────────────────────────────────────────────────────
    def _used_last_minute(self) -> int:
        cutoff = time.monotonic() - 60.0
        while self._sent and self._sent[0][0] < cutoff:
            self._sent.popleft()
        return sum(n for _, n in self._sent)

    def _wait_for_capacity(self, n: int, deadline: float) -> None:
        while self._used_last_minute() + n > self._per_minute:
            oldest_ts = self._sent[0][0]
            sleep_for = max(0.5, oldest_ts + 60.0 - time.monotonic())
            if time.monotonic() + sleep_for > deadline:
                raise EmbeddingError(f"rate-limit wait would exceed max_wait_seconds={self._max_wait}")
            logger.info("embedding_rate_limit_pacing", sleep=round(sleep_for, 1), pending=n)
            time.sleep(sleep_for)

    # ── one API call ──────────────────────────────────────────────────────
    def _embed_batch(self, chunk: list[str], deadline: float) -> list[list[float]]:
        attempt = 0
        while True:
            attempt += 1
            self._sent.append((time.monotonic(), len(chunk)))
            try:
                resp = self._client.models.embed_content(
                    model=self._model,
                    contents=chunk,
                    config=types.EmbedContentConfig(
                        task_type="SEMANTIC_SIMILARITY",
                        output_dimensionality=self.dimensions,
                    ),
                )
                break
            except Exception as exc:  # SDK raises several types; inspect the text
                msg = str(exc)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                    quota = _quota_details(msg)
                    if "PerDay" in quota.get("quotaId", ""):
                        # Daily cap: no point waiting, and retries count against it.
                        self._daily_exhausted = True
                        logger.warning("embedding_daily_quota_exhausted", **quota)
                        raise EmbeddingQuotaExhausted(f"daily quota exhausted: {quota}") from exc
                    # Per-minute cap: wait a full window, then retry.
                    m = _RETRY_DELAY.search(msg)
                    suggested = float(m.group(1)) + 1.0 if m else 0.0
                    delay = min(max(suggested, 61.0), 90.0)   # never less than one full window
                    reason = "embedding_429_backoff"
                elif _CLIENT_ERROR.search(msg):
                    # Bad request / auth / unknown model: retrying will not help.
                    raise EmbeddingError(msg[:300]) from exc
                else:
                    # Network blip, truncated response, 5xx: short linear backoff.
                    delay = 3.0 * attempt
                    reason = "embedding_transient_retry"
                if attempt >= _MAX_ATTEMPTS or time.monotonic() + delay > deadline:
                    raise EmbeddingError(f"{reason}: {msg[:200]}") from exc
                logger.warning(reason, attempt=attempt, sleep=delay, error=msg[:120], **_quota_details(msg))
                time.sleep(delay)
                continue

        vectors = [list(e.values) for e in (resp.embeddings or [])]
        if len(vectors) != len(chunk):
            raise EmbeddingError(f"expected {len(chunk)} embeddings, got {len(vectors)}")
        if vectors and len(vectors[0]) != self.dimensions:
            raise EmbeddingError(f"expected {self.dimensions}-dim vectors, got {len(vectors[0])}")
        return vectors
