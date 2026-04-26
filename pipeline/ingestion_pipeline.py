import logging
import time
from services.fetchers.base_fetcher import NewsFetcher
from services.clustering_service import ClusteringService
from services.summarization_service import SummarizationService
from db.repositories.article_repository import ArticleRepository
from db.repositories.source_repository import SourceRepository
from db.repositories.summary_repository import SummaryRepository

logger = logging.getLogger(__name__)


class IngestionPipeline:

    def __init__(
        self,
        fetcher: NewsFetcher,
        article_repo: ArticleRepository,
        source_repo: SourceRepository,
        summary_repo: SummaryRepository,
        clustering_service: ClusteringService,
        summarization_service: SummarizationService,
        summarization_delay_seconds: float = 4.0,
    ):
        self._fetcher               = fetcher
        self._article_repo          = article_repo
        self._source_repo           = source_repo
        self._summary_repo          = summary_repo
        self._clustering_service    = clustering_service
        self._summarization_service = summarization_service
        self._summarization_delay   = summarization_delay_seconds

    def run(self):
        new_cluster_ids = []

        for category in self._fetcher.supported_categories():
            logger.info("Fetching category: %s", category)
            articles = self._fetcher.fetch(category)
            logger.info("Fetched %d articles for %s", len(articles), category)

            for article in articles:
                # Skip if already ingested
                if self._article_repo.exists_by_url(article.url):
                    continue

                # Resolve source
                article.source = self._source_repo.find_or_create(article.source)

                # Find matching cluster or create new
                cluster, is_new = self._clustering_service.find_or_create_cluster(
                    article, category
                )
                article.cluster_id = cluster.id

                # Save article
                self._article_repo.save(article)
                logger.info(
                    "%s cluster #%d: %s",
                    "[NEW CLUSTER]" if is_new else "[ADDED TO]",
                    cluster.id,
                    article.title[:70],
                )

                if is_new:
                    new_cluster_ids.append(cluster.id)

        # Summarize all new clusters with rate limiting
        logger.info("Summarizing %d new clusters...", len(new_cluster_ids))
        for i, cluster_id in enumerate(new_cluster_ids):
            summary = self._summarization_service.summarize(cluster_id)
            if summary:
                self._summary_repo.save(summary)
                logger.info("Summarized cluster #%d", cluster_id)
            else:
                logger.warning("Failed to summarize cluster #%d", cluster_id)

            # Rate limit: stay under 15 requests/min on free tier
            if i < len(new_cluster_ids) - 1:
                time.sleep(self._summarization_delay)

        logger.info("Done. %d new clusters created and summarized.", len(new_cluster_ids))
