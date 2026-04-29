"""
LLM worker — long-running.

Polls the summarization queue. For each cluster, asks the configured LLM
(Groq with Gemini fallback by default — see settings) for a summary, writes
it AND the cluster's authoritative category in one transaction, then acks
the queue row.

Multiple instances may run concurrently; the queue uses
SELECT ... FOR UPDATE SKIP LOCKED so they never collide.
"""
from __future__ import annotations
import os
import time

from dotenv import load_dotenv
load_dotenv()

from infra.logging_config import configure_logging  # noqa: E402
configure_logging(level=os.getenv("LOG_LEVEL", "INFO"))

import structlog  # noqa: E402

from config.settings import Settings  # noqa: E402
from db.connection import DatabasePool  # noqa: E402
from db.repositories.article_repository import ArticleRepository  # noqa: E402
from db.repositories.summary_repository import SummaryRepository  # noqa: E402
from db.repositories.queue_repository import QueueRepository  # noqa: E402
from services.summarization_service import SummarizationService  # noqa: E402
from infra.llm import (  # noqa: E402
    LLMQuotaExhausted,
    GroqLLMClient,
    GeminiLLMClient,
    FallbackLLMClient,
    ProviderState,
)
from infra.rate_limiter import TokenRateLimiter  # noqa: E402

logger = structlog.get_logger(__name__)

# Conservative estimate per call (prompt + completion).
TOKENS_PER_CALL = 1_500


def _build_llm(settings: Settings, log) -> FallbackLLMClient:
    """Construct a FallbackLLMClient from whichever provider keys are configured."""
    providers: list[ProviderState] = []

    if settings.groq_api_key:
        providers.append(ProviderState(
            client=GroqLLMClient(settings.groq_api_key, settings.groq_model),
            limiter=TokenRateLimiter(daily_limit=settings.groq_daily_token_budget),
        ))
        log.info("provider_registered", provider="groq", budget=settings.groq_daily_token_budget)

    if settings.gemini_api_key:
        providers.append(ProviderState(
            client=GeminiLLMClient(settings.gemini_api_key, settings.gemini_model),
            limiter=TokenRateLimiter(daily_limit=settings.gemini_daily_token_budget),
        ))
        log.info("provider_registered", provider="gemini", budget=settings.gemini_daily_token_budget)

    if not providers:
        raise RuntimeError(
            "No LLM provider configured. Set GROQ_API_KEY and/or GEMINI_API_KEY in your .env"
        )

    return FallbackLLMClient(providers, tokens_per_call=TOKENS_PER_CALL)


def run() -> None:
    settings = Settings.from_env()
    log = logger.bind(worker="llm")

    pool = DatabasePool(settings)
    article_repo = ArticleRepository(pool)
    summary_repo = SummaryRepository(pool)
    queue_repo = QueueRepository(pool)

    llm = _build_llm(settings, log)
    svc = SummarizationService(article_repo, settings, llm=llm)

    idle_sleep = settings.llm_worker_idle_seconds
    inter_call_sleep = settings.summarization_delay_seconds
    stuck_minutes = settings.queue_stuck_minutes
    max_attempts = settings.queue_max_attempts

    log.info("worker_started", idle_sleep=idle_sleep, max_attempts=max_attempts)

    try:
        while True:
            if not llm.has_capacity():
                log.warning("all_providers_exhausted_sleeping", status=llm.status())
                time.sleep(idle_sleep)
                continue

            cluster_id = queue_repo.claim_one(max_attempts=max_attempts)
            if cluster_id is None:
                released = queue_repo.release_stale(stuck_minutes)
                swept = queue_repo.sweep_exhausted(max_attempts=max_attempts)
                if released or swept:
                    log.info("queue_maintenance", released=released, swept=swept)
                time.sleep(idle_sleep)
                continue

            clog = log.bind(cluster_id=cluster_id)
            try:
                summary = svc.summarize(cluster_id)
                if summary is None:
                    queue_repo.mark_failed(cluster_id, "summary_null")
                    clog.warning("summary_null")
                    continue

                summary_repo.save(summary)  # writes summary + cluster.category in 1 tx
                queue_repo.mark_done(cluster_id)
                clog.info("summarized", category=summary.category)

            except LLMQuotaExhausted as exc:
                # All providers reported daily-quota exhausted. Release for tomorrow.
                queue_repo.release(cluster_id)
                clog.warning("all_quota_exhausted", err=str(exc))
                time.sleep(idle_sleep)
                continue

            except Exception as exc:
                # Unknown errors are usually transient (5xx, network blip, parse glitch).
                # Release for retry — the queue's attempts counter caps total tries.
                queue_repo.release(cluster_id)
                clog.warning("transient_failure_released", err=str(exc))

            time.sleep(inter_call_sleep)

    except KeyboardInterrupt:
        log.info("worker_shutdown_requested")
    finally:
        pool.close_all()


if __name__ == "__main__":
    run()
