"""
AnalysisAgent — LangGraph node that summarizes every newly-created cluster
via Groq, subject to a daily token budget.

Rate limit handling:
  - TPD (tokens per day) exhausted  → stop the loop immediately, record skipped clusters
  - RPM (requests per minute) limit → retry with exponential backoff (up to 3×)
  - Other Groq API errors           → retry with exponential backoff (up to 3×)
"""
from __future__ import annotations
import time
import structlog

from groq import RateLimitError, APIError
from infra.rate_limiter import TokenRateLimiter
from infra.retry import with_retry
from services.summarization_service import SummarizationService
from db.repositories.summary_repository import SummaryRepository
from agents.state import PipelineState

logger = structlog.get_logger(__name__)

# Conservative token estimate per summarization call (prompt + completion).
_TOKENS_PER_CALL = 1_500


def _is_daily_limit(exc: RateLimitError) -> bool:
    """Return True when Groq's 'tokens per day' quota is exhausted."""
    return "tokens per day" in str(exc).lower() or "tpd" in str(exc).lower()


class AnalysisAgent:

    def __init__(
        self,
        summarization_service: SummarizationService,
        summary_repo: SummaryRepository,
        rate_limiter: TokenRateLimiter,
        inter_call_delay: float = 2.0,
    ) -> None:
        self._svc = summarization_service
        self._summary_repo = summary_repo
        self._rate_limiter = rate_limiter
        self._delay = inter_call_delay

    def __call__(self, state: PipelineState) -> dict:
        cluster_ids = state["new_cluster_ids"]
        log = logger.bind(run_id=state["run_id"], agent="analysis", total=len(cluster_ids))

        if not cluster_ids:
            log.info("no_clusters_to_summarize")
            return {"summaries_created": 0, "analysis_errors": [], "phase": "trend"}

        summaries_created = 0
        errors: list[str] = []

        for i, cluster_id in enumerate(cluster_ids):
            # Pre-flight budget check (in-process counter)
            if not self._rate_limiter.can_use(_TOKENS_PER_CALL):
                log.warning(
                    "budget_exhausted",
                    remaining=self._rate_limiter.remaining,
                    skipped=len(cluster_ids) - i,
                )
                errors.append(f"budget_exhausted:skipped_from_cluster:{cluster_id}")
                break

            try:
                summary = self._call_with_retry(cluster_id)
                if summary:
                    self._summary_repo.save(summary)
                    self._rate_limiter.consume(_TOKENS_PER_CALL)
                    summaries_created += 1
                    log.info("summarized", cluster_id=cluster_id, progress=f"{i + 1}/{len(cluster_ids)}")
                else:
                    errors.append(f"null_summary:cluster:{cluster_id}")
                    log.warning("null_summary", cluster_id=cluster_id)

            except RateLimitError as exc:
                if _is_daily_limit(exc):
                    # Daily quota is gone — no point calling again today.
                    skipped = len(cluster_ids) - i
                    log.warning(
                        "daily_token_quota_exhausted",
                        cluster_id=cluster_id,
                        skipped_clusters=skipped,
                    )
                    errors.append(f"daily_quota_exhausted:skipped_from_cluster:{cluster_id}")
                    break
                # Per-minute limit — already retried inside _call_with_retry; give up on this cluster.
                errors.append(f"rate_limit:cluster:{cluster_id}:{exc}")
                log.error("rate_limit_exhausted", cluster_id=cluster_id, error=str(exc))

            except Exception as exc:
                errors.append(f"cluster:{cluster_id}:{exc}")
                log.error("summarization_failed", cluster_id=cluster_id, error=str(exc))

            if i < len(cluster_ids) - 1:
                time.sleep(self._delay)

        log.info("analysis_done", created=summaries_created, errors=len(errors))
        return {
            "summaries_created": summaries_created,
            "analysis_errors": errors,
            "phase": "trend",
        }

    @with_retry(max_attempts=3, backoff_base=2.0, exceptions=(APIError,))
    def _call_with_retry(self, cluster_id: int):
        """
        Retry on transient APIError only.
        RateLimitError is intentionally excluded — the caller decides whether
        to retry (RPM) or stop entirely (TPD).
        """
        return self._svc.summarize(cluster_id)
