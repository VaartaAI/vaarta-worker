"""
Application metrics, exported via OpenTelemetry to whichever OTLP endpoint
infra/observability.py was pointed at (Grafana Cloud in our case).

Counters & histograms: increment / record from anywhere by importing the
module-level objects.

Observable gauges: their value is computed at scrape time by calling a
"provider" function. Workers that have access to live state (DB pool,
Redis client) register their providers via the register_*() helpers
below before the first export window.
"""
from __future__ import annotations
import logging
from typing import Callable

from opentelemetry import metrics
from opentelemetry.metrics import Observation

logger = logging.getLogger(__name__)

_meter = metrics.get_meter("vaarta-worker")

# ────────────────────────────────────────────────────────────────────────
# Counters — monotonically increasing
# ────────────────────────────────────────────────────────────────────────

articles_fetched_total = _meter.create_counter(
    "vaarta.articles.fetched",
    description="Raw articles received from sources, before dedup/clustering",
)

articles_saved_total = _meter.create_counter(
    "vaarta.articles.saved",
    description="Articles persisted to Postgres",
)

clusters_created_total = _meter.create_counter(
    "vaarta.clusters.created",
    description="Brand-new event clusters discovered during ingest",
)

summaries_total = _meter.create_counter(
    "vaarta.summaries.created",
    description="Summaries successfully written to DB",
)

summary_failures_total = _meter.create_counter(
    "vaarta.summaries.failed",
    description="Summary attempts that failed (parse error, transient, etc.)",
)

provider_exhausted_total = _meter.create_counter(
    "vaarta.provider.exhausted",
    description="Times an LLM provider hit its daily quota",
)

provider_used_total = _meter.create_counter(
    "vaarta.provider.used",
    description="Successful LLM calls per provider",
)

budget_overrun_total = _meter.create_counter(
    "vaarta.budget.overrun",
    description="Times budget consumption pushed past the daily limit",
)

# ────────────────────────────────────────────────────────────────────────
# Histograms — distributions
# ────────────────────────────────────────────────────────────────────────

llm_latency_seconds = _meter.create_histogram(
    "vaarta.llm.latency",
    description="Latency of one LLM call (prompt → response)",
    unit="s",
)

summary_tokens_used = _meter.create_histogram(
    "vaarta.summary.tokens",
    description="Actual tokens used per summary call (input + output)",
)

# ────────────────────────────────────────────────────────────────────────
# Observable gauges — current state, sampled at export time
# ────────────────────────────────────────────────────────────────────────

# Module-level holders that workers populate via register_*().
# A "None" provider means the gauge yields nothing for this process.
_queue_depth_provider: Callable[[], dict[str, int]] | None = None
_budget_provider: Callable[[], dict[str, dict[str, int]]] | None = None


def register_queue_depth_provider(fn: Callable[[], dict[str, int]]) -> None:
    """
    Workers call this to enable the queue.depth gauge in this process.
    `fn` must return a dict like {"pending": 487, "in_progress": 1}.
    """
    global _queue_depth_provider
    _queue_depth_provider = fn


def register_budget_provider(fn: Callable[[], dict[str, dict[str, int]]]) -> None:
    """
    Workers call this to enable the budget.tokens gauge.
    `fn` must return e.g. {"groq": {"used": 14035, "remaining": 75965}, ...}.
    """
    global _budget_provider
    _budget_provider = fn


def _queue_depth_observe(options):  # noqa: ARG001 (OTel passes options)
    if _queue_depth_provider is None:
        return
    try:
        for status, count in _queue_depth_provider().items():
            yield Observation(count, {"status": status})
    except Exception as exc:
        logger.warning("queue_depth_observe_failed: %s", exc)


def _budget_observe(options):  # noqa: ARG001
    if _budget_provider is None:
        return
    try:
        for provider, data in _budget_provider().items():
            yield Observation(data.get("used", 0), {"provider": provider, "kind": "used"})
            yield Observation(data.get("remaining", 0), {"provider": provider, "kind": "remaining"})
    except Exception as exc:
        logger.warning("budget_observe_failed: %s", exc)


_meter.create_observable_gauge(
    "vaarta.queue.depth",
    callbacks=[_queue_depth_observe],
    description="Summarization-queue rows by status (pending / in_progress)",
)

_meter.create_observable_gauge(
    "vaarta.budget.tokens",
    callbacks=[_budget_observe],
    description="Per-provider token budget — used and remaining today",
)
