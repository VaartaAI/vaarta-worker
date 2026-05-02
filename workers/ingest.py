"""
Ingestion worker — one-shot.

Iterates over every source in config/sources.yaml, dedupes by URL, clusters
articles by title similarity, persists, and enqueues new clusters for the
LLM worker. Designed to be triggered by cron / a scheduler.
"""
from __future__ import annotations
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from infra.logging_config import configure_logging  # noqa: E402
configure_logging(level=os.getenv("LOG_LEVEL", "INFO"))

from infra.observability import configure_observability  # noqa: E402
configure_observability(service_name="vaarta-ingest")

import structlog  # noqa: E402

from config.settings import Settings  # noqa: E402
from db.connection import DatabasePool  # noqa: E402
from db.repositories.article_repository import ArticleRepository  # noqa: E402
from db.repositories.cluster_repository import ClusterRepository  # noqa: E402
from db.repositories.source_repository import SourceRepository  # noqa: E402
from infra.queue import Queue, PostgresQueue  # noqa: E402
from infra import metrics as m  # noqa: E402
from services.clustering_service import ClusteringService  # noqa: E402
from services.sources import build_sources  # noqa: E402

logger = structlog.get_logger(__name__)

SOURCES_YAML = Path(__file__).resolve().parent.parent / "config" / "sources.yaml"


def run() -> None:
    settings = Settings.from_env()
    log = logger.bind(worker="ingest")

    pool = DatabasePool(settings)
    article_repo = ArticleRepository(pool)
    cluster_repo = ClusterRepository(pool)
    source_repo = SourceRepository(pool)
    queue: Queue = PostgresQueue(pool)
    clustering = ClusteringService(cluster_repo, settings)

    sources = build_sources(SOURCES_YAML, settings)
    log.info("sources_loaded", count=len(sources))

    articles_saved = 0
    new_clusters = 0
    errors = 0

    for source in sources:
        slog = log.bind(source=source.name)
        try:
            articles = list(source.fetch())
        except Exception as exc:
            errors += 1
            slog.error("fetch_failed", error=str(exc))
            continue
        slog.info("fetched", count=len(articles))
        m.articles_fetched_total.add(len(articles), {"source": source.name})

        for article in articles:
            try:
                if article_repo.exists_by_url(article.url):
                    continue
                article.source = source_repo.find_or_create(article.source)
                cluster, is_new = clustering.find_or_create_cluster(article)
                article.cluster_id = cluster.id
                article_repo.save(article)
                articles_saved += 1
                m.articles_saved_total.add(1, {"source": source.name})
                if is_new:
                    new_clusters += 1
                    queue.enqueue(cluster.id)
                    m.clusters_created_total.add(1, {"source": source.name})
                    slog.info("cluster_created", cluster_id=cluster.id, title=article.title[:80])
            except Exception as exc:
                errors += 1
                slog.error("article_failed", url=article.url, error=str(exc))

    log.info(
        "ingest_complete",
        articles_saved=articles_saved,
        new_clusters=new_clusters,
        errors=errors,
    )
    pool.close_all()


if __name__ == "__main__":
    run()
