#!/usr/bin/env python3
"""
CLI for running individual pipeline phases or the full pipeline.

Usage:
    python scripts/run_agent.py                # full pipeline
    python scripts/run_agent.py --phase trend  # trend scoring only
    python scripts/run_agent.py --dry-run      # ingestion only (no summarization, no trend)
    python scripts/run_agent.py --categories politics,tech

Must be run from the repo root:
    cd vaarta-worker && python scripts/run_agent.py
"""
import sys
import argparse
sys.path.insert(0, ".")

from infra.logging_config import configure_logging
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
from agents.state import initial_state, PipelineState

logger = structlog.get_logger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="VaartaAI pipeline runner")
    parser.add_argument(
        "--phase",
        choices=["full", "ingestion", "analysis", "trend"],
        default="full",
        help="Which phase(s) to run (default: full)",
    )
    parser.add_argument(
        "--categories",
        default="",
        help="Comma-separated list of categories to fetch (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run ingestion only; do not summarize or score trends",
    )
    return parser.parse_args()


def _build_deps(settings: Settings):
    db_pool = DatabasePool(settings)
    return {
        "db_pool":     db_pool,
        "article_repo": ArticleRepository(db_pool),
        "cluster_repo": ClusterRepository(db_pool),
        "source_repo":  SourceRepository(db_pool),
        "summary_repo": SummaryRepository(db_pool),
        "fetcher":      NewsAPIFetcher(settings),
        "clustering":   ClusteringService(ClusterRepository(db_pool), settings),
        "summarizing":  SummarizationService(ArticleRepository(db_pool), settings),
        "rate_limiter": TokenRateLimiter(daily_limit=settings.groq_daily_token_budget),
    }


def main() -> None:
    args = parse_args()
    settings = Settings.from_env()
    log = logger.bind(phase=args.phase, dry_run=args.dry_run)
    log.info("runner_starting")

    deps = _build_deps(settings)

    ingestion_agent = IngestionAgent(
        deps["fetcher"], deps["article_repo"], deps["source_repo"], deps["clustering"]
    )
    analysis_agent = AnalysisAgent(
        deps["summarizing"], deps["summary_repo"], deps["rate_limiter"],
        inter_call_delay=settings.summarization_delay_seconds,
    )
    trend_agent = TrendAgent(deps["cluster_repo"])

    categories = [c.strip() for c in args.categories.split(",") if c.strip()]
    state = initial_state(categories=categories)

    if args.dry_run or args.phase == "ingestion":
        result = ingestion_agent(state)
        log.info("ingestion_result", **{k: v for k, v in result.items() if k != "new_cluster_ids"})
        log.info("new_cluster_ids", ids=result.get("new_cluster_ids", []))

    elif args.phase == "trend":
        result = trend_agent(state)
        log.info("trend_result", **result)

    elif args.phase == "analysis":
        # Manual cluster IDs required for analysis-only mode
        if not state["new_cluster_ids"]:
            log.warning("no_cluster_ids_provided", hint="Pass cluster IDs by editing state or use --phase full")
        result = analysis_agent(state)
        log.info("analysis_result", **{k: v for k, v in result.items() if k != "analysis_errors"})

    else:  # full pipeline via graph
        from graph.orchestrator import build_pipeline
        pipeline = build_pipeline(ingestion_agent, analysis_agent, trend_agent)
        final = pipeline.invoke(state)
        log.info(
            "pipeline_complete",
            run_id=final["run_id"],
            articles_fetched=final["articles_fetched"],
            new_clusters=len(final["new_cluster_ids"]),
            summaries_created=final["summaries_created"],
            trend_updates=final["trend_updates"],
            ingestion_errors=len(final["ingestion_errors"]),
            analysis_errors=len(final["analysis_errors"]),
        )

    deps["db_pool"].close_all()


if __name__ == "__main__":
    main()
