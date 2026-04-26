"""
VaartaAI worker entrypoint.

Bootstraps all dependencies and runs the LangGraph agentic pipeline:
    ingestion → analysis → trend → done
"""
# Configure structured logging before any other import that might log.
from infra.logging_config import configure_logging

# Settings are needed for log level, so load them first.
import os
from dotenv import load_dotenv
load_dotenv()
configure_logging(level=os.getenv("LOG_LEVEL", "INFO"))

import structlog

from config.settings import Settings
from db.connection import DatabasePool
from db.repositories.article_repository import ArticleRepository
from db.repositories.cluster_repository import ClusterRepository
from db.repositories.source_repository import SourceRepository
from db.repositories.summary_repository import SummaryRepository
from services.fetchers.newsapi_fetcher import NewsAPIFetcher
from services.clustering_service import ClusteringService
from services.summarization_service import SummarizationService
from infra.rate_limiter import TokenRateLimiter
from agents.ingestion_agent import IngestionAgent
from agents.analysis_agent import AnalysisAgent
from agents.trend_agent import TrendAgent
from graph.orchestrator import build_pipeline
from agents.state import initial_state

logger = structlog.get_logger(__name__)


def main() -> None:
    settings = Settings.from_env()
    log = logger.bind(service="vaarta-worker")
    log.info("pipeline_starting")

    # ── Database ─────────────────────────────────────────────────────────
    db_pool = DatabasePool(settings)

    article_repo = ArticleRepository(db_pool)
    cluster_repo = ClusterRepository(db_pool)
    source_repo  = SourceRepository(db_pool)
    summary_repo = SummaryRepository(db_pool)

    # ── Domain services ───────────────────────────────────────────────────
    fetcher               = NewsAPIFetcher(settings)
    clustering_service    = ClusteringService(cluster_repo, settings)
    summarization_service = SummarizationService(article_repo, settings)

    # ── Infrastructure ────────────────────────────────────────────────────
    rate_limiter = TokenRateLimiter(daily_limit=settings.groq_daily_token_budget)

    # ── Agents ────────────────────────────────────────────────────────────
    ingestion_agent = IngestionAgent(fetcher, article_repo, source_repo, clustering_service)
    analysis_agent  = AnalysisAgent(
        summarization_service,
        summary_repo,
        rate_limiter,
        inter_call_delay=settings.summarization_delay_seconds,
    )
    trend_agent = TrendAgent(cluster_repo)

    # ── Graph ─────────────────────────────────────────────────────────────
    pipeline = build_pipeline(ingestion_agent, analysis_agent, trend_agent)

    final_state = pipeline.invoke(initial_state(categories=[]))

    log.info(
        "pipeline_complete",
        run_id=final_state["run_id"],
        articles_fetched=final_state["articles_fetched"],
        new_clusters=len(final_state["new_cluster_ids"]),
        summaries_created=final_state["summaries_created"],
        trend_updates=final_state["trend_updates"],
        ingestion_errors=len(final_state["ingestion_errors"]),
        analysis_errors=len(final_state["analysis_errors"]),
    )

    db_pool.close_all()


if __name__ == "__main__":
    main()
