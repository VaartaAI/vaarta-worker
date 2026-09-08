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

from infra.observability import configure_observability  # noqa: E402
configure_observability(service_name="vaarta-llm")

import psycopg2  # noqa: E402
import structlog  # noqa: E402

from config.settings import Settings  # noqa: E402
from db.connection import DatabasePool  # noqa: E402
from db.repositories.article_repository import ArticleRepository  # noqa: E402
from db.repositories.summary_repository import SummaryRepository  # noqa: E402
from infra.queue import Queue, PostgresQueue  # noqa: E402
from services.summarization_service import SummarizationService  # noqa: E402
from infra.llm import (  # noqa: E402
    LLMQuotaExhausted,
    GroqLLMClient,
    GeminiLLMClient,
    FallbackLLMClient,
    ProviderState,
)
from infra.budget import TokenBudget, InMemoryTokenBudget, RedisTokenBudget  # noqa: E402
from infra import metrics as m  # noqa: E402

logger = structlog.get_logger(__name__)

# Conservative estimate per call (prompt + completion).
TOKENS_PER_CALL = 1_500

# Backoff for Postgres connection errors in the main loop (seconds).
DB_RETRY_BASE_SECONDS = 5
DB_RETRY_MAX_SECONDS = 120


def _release_safely(queue: Queue, cluster_id: int, clog) -> None:
    """
    Put a claimed row back to pending. If the database is unreachable at this
    moment, don't let that crash the worker: the row stays in_progress and
    release_stale() frees it once queue_stuck_minutes have passed.
    """
    try:
        queue.release(cluster_id)
    except psycopg2.Error as exc:
        clog.warning("release_failed_db_error", err=str(exc).strip())


def _build_llm(settings: Settings, log) -> FallbackLLMClient:
    """Construct a FallbackLLMClient from whichever provider keys are configured."""

    # Decide budget backend once. If REDIS_URL is set and reachable, all
    # providers share Redis counters — multiple LLM workers honour ONE budget.
    # Otherwise fall back to per-process in-memory counters.
    redis_client = None
    if settings.redis_url:
        try:
            import redis  # local import: optional dependency
            redis_client = redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_timeout=5.0,         # don't hang the worker if Redis stalls
                socket_connect_timeout=5.0,
            )
            redis_client.ping()
            log.info("budget_backend", backend="redis")
        except Exception as exc:
            log.warning("redis_unavailable_using_memory", error=str(exc))
            redis_client = None
    else:
        log.info("budget_backend", backend="memory")

    def make_budget(provider: str, daily_limit: int) -> TokenBudget:
        if redis_client is not None:
            return RedisTokenBudget(redis_client, provider, daily_limit)
        return InMemoryTokenBudget(daily_limit=daily_limit)

    providers: list[ProviderState] = []

    if settings.groq_api_key:
        providers.append(ProviderState(
            client=GroqLLMClient(settings.groq_api_key, settings.groq_model),
            limiter=make_budget("groq", settings.groq_daily_token_budget),
        ))
        log.info("provider_registered", provider="groq", budget=settings.groq_daily_token_budget)

    if settings.gemini_api_key:
        providers.append(ProviderState(
            client=GeminiLLMClient(settings.gemini_api_key, settings.gemini_model),
            limiter=make_budget("gemini", settings.gemini_daily_token_budget),
        ))
        log.info("provider_registered", provider="gemini", budget=settings.gemini_daily_token_budget)

    if not providers:
        raise RuntimeError(
            "No LLM provider configured. Set GROQ_API_KEY and/or GEMINI_API_KEY in your .env"
        )

    return FallbackLLMClient(providers, tokens_per_call=TOKENS_PER_CALL)


def _register_metric_gauges(pool: DatabasePool, llm: FallbackLLMClient) -> None:
    """Wire observable gauges to live state. Called once at worker startup."""

    def queue_depth() -> dict[str, int]:
        conn = pool.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status, COUNT(*) FROM summarization_queue "
                    "WHERE status IN ('pending', 'in_progress') GROUP BY status"
                )
                return {row[0]: row[1] for row in cur.fetchall()}
        finally:
            pool.release_connection(conn)

    def budget_state() -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for p in llm._providers:  # noqa: SLF001  (intentional: same package)
            try:
                out[p.client.name] = {
                    "used": p.limiter._daily_limit - p.limiter.remaining,  # noqa: SLF001
                    "remaining": p.limiter.remaining,
                }
            except Exception:
                pass
        return out

    m.register_queue_depth_provider(queue_depth)
    m.register_budget_provider(budget_state)


def run() -> None:
    settings = Settings.from_env()
    log = logger.bind(worker="llm")

    pool = DatabasePool(settings)
    article_repo = ArticleRepository(pool)
    summary_repo = SummaryRepository(pool)
    queue: Queue = PostgresQueue(pool)

    llm = _build_llm(settings, log)
    svc = SummarizationService(article_repo, settings, llm=llm)

    # Observable gauges: providers query live state when OTel scrapes.
    _register_metric_gauges(pool, llm)

    idle_sleep = settings.llm_worker_idle_seconds
    inter_call_sleep = settings.summarization_delay_seconds
    stuck_minutes = settings.queue_stuck_minutes
    max_attempts = settings.queue_max_attempts

    log.info("worker_started", idle_sleep=idle_sleep, max_attempts=max_attempts)

    db_failures = 0
    try:
        while True:
            if not llm.has_capacity():
                log.warning("all_providers_exhausted_sleeping", status=llm.status())
                time.sleep(idle_sleep)
                continue

            try:
                cluster_id = queue.claim_one(max_attempts=max_attempts)
                if cluster_id is None:
                    released = queue.release_stale(stuck_minutes)
                    swept = queue.sweep_exhausted(max_attempts=max_attempts)
                    if released or swept:
                        log.info("queue_maintenance", released=released, swept=swept)
                    time.sleep(idle_sleep)
                    continue
            except psycopg2.Error as exc:
                # Postgres unreachable or the connection dropped (common with a
                # remote Neon endpoint). The pool has already discarded the dead
                # socket; back off and retry instead of crashing the daemon. Any
                # row left in_progress is recovered by release_stale() later.
                db_failures += 1
                backoff = min(DB_RETRY_BASE_SECONDS * 2 ** (db_failures - 1), DB_RETRY_MAX_SECONDS)
                log.warning("db_error_retrying", err=str(exc).strip(), failures=db_failures, sleep=backoff)
                time.sleep(backoff)
                continue
            db_failures = 0

            clog = log.bind(cluster_id=cluster_id)
            try:
                summary = svc.summarize(cluster_id)
                if summary is None:
                    queue.mark_failed(cluster_id, "summary_null")
                    m.summary_failures_total.add(1, {"reason": "summary_null"})
                    clog.warning("summary_null")
                    continue

                summary_repo.save(summary)  # writes summary + cluster.category in 1 tx
                queue.mark_done(cluster_id)
                m.summaries_total.add(1, {"category": summary.category or "unknown"})
                clog.info("summarized", category=summary.category)

            except LLMQuotaExhausted as exc:
                # All providers reported daily-quota exhausted. Release for tomorrow.
                _release_safely(queue, cluster_id, clog)
                m.summary_failures_total.add(1, {"reason": "quota_exhausted"})
                clog.warning("all_quota_exhausted", err=str(exc))
                time.sleep(idle_sleep)
                continue

            except Exception as exc:
                # Unknown errors are usually transient (5xx, network blip, parse glitch).
                # Release for retry — the queue's attempts counter caps total tries.
                _release_safely(queue, cluster_id, clog)
                m.summary_failures_total.add(1, {"reason": "transient"})
                clog.warning("transient_failure_released", err=str(exc))

            time.sleep(inter_call_sleep)

    except KeyboardInterrupt:
        log.info("worker_shutdown_requested")
    finally:
        pool.close_all()


if __name__ == "__main__":
    run()
