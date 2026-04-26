"""
IngestionAgent — LangGraph node responsible for fetching news articles,
deduplicating them, clustering, and persisting to the database.

Returns a partial PipelineState dict that LangGraph merges via reducers.
"""
from __future__ import annotations
import structlog

from services.fetchers.base_fetcher import NewsFetcher
from services.clustering_service import ClusteringService
from db.repositories.article_repository import ArticleRepository
from db.repositories.source_repository import SourceRepository
from agents.state import PipelineState

logger = structlog.get_logger(__name__)


class IngestionAgent:

    def __init__(
        self,
        fetcher: NewsFetcher,
        article_repo: ArticleRepository,
        source_repo: SourceRepository,
        clustering_service: ClusteringService,
    ) -> None:
        self._fetcher = fetcher
        self._article_repo = article_repo
        self._source_repo = source_repo
        self._clustering_service = clustering_service

    def __call__(self, state: PipelineState) -> dict:
        new_cluster_ids: list[int] = []
        articles_fetched: int = 0
        errors: list[str] = []

        categories = state["categories"] or self._fetcher.supported_categories()
        log = logger.bind(run_id=state["run_id"], agent="ingestion")

        for category in categories:
            try:
                log.info("fetching_category", category=category)
                articles = self._fetcher.fetch(category)
                log.info("fetched", category=category, count=len(articles))
            except Exception as exc:
                errors.append(f"category:{category}:{exc}")
                log.error("fetch_failed", category=category, error=str(exc))
                continue

            for article in articles:
                try:
                    if self._article_repo.exists_by_url(article.url):
                        continue

                    article.source = self._source_repo.find_or_create(article.source)
                    cluster, is_new = self._clustering_service.find_or_create_cluster(
                        article, category
                    )
                    article.cluster_id = cluster.id
                    self._article_repo.save(article)
                    articles_fetched += 1

                    if is_new:
                        new_cluster_ids.append(cluster.id)
                        log.info(
                            "cluster_created",
                            cluster_id=cluster.id,
                            title=article.title[:80],
                        )
                    else:
                        log.debug(
                            "article_added",
                            cluster_id=cluster.id,
                            title=article.title[:80],
                        )
                except Exception as exc:
                    errors.append(f"article:{article.url}:{exc}")
                    log.error("article_failed", url=article.url, error=str(exc))

        log.info(
            "ingestion_done",
            new_clusters=len(new_cluster_ids),
            articles_saved=articles_fetched,
            errors=len(errors),
        )

        return {
            "new_cluster_ids": new_cluster_ids,
            "articles_fetched": articles_fetched,
            "ingestion_errors": errors,
            "phase": "analysis",
        }
