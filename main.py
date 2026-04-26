import logging
from config.settings import Settings
from db.connection import DatabasePool
from db.repositories.article_repository import ArticleRepository
from db.repositories.cluster_repository import ClusterRepository
from db.repositories.source_repository import SourceRepository
from db.repositories.summary_repository import SummaryRepository
from services.fetchers.newsapi_fetcher import NewsAPIFetcher
from services.clustering_service import ClusteringService
from services.summarization_service import SummarizationService
from pipeline.ingestion_pipeline import IngestionPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    logger.info("Starting VaartaAI ingestion pipeline")

    settings = Settings.from_env()
    db_pool = DatabasePool(settings)

    article_repo = ArticleRepository(db_pool)
    cluster_repo = ClusterRepository(db_pool)
    source_repo  = SourceRepository(db_pool)
    summary_repo = SummaryRepository(db_pool)

    fetcher               = NewsAPIFetcher(settings)
    clustering_service    = ClusteringService(cluster_repo, settings)
    summarization_service = SummarizationService(article_repo, settings)

    pipeline = IngestionPipeline(
        fetcher=fetcher,
        article_repo=article_repo,
        source_repo=source_repo,
        summary_repo=summary_repo,
        clustering_service=clustering_service,
        summarization_service=summarization_service,
        summarization_delay_seconds=settings.summarization_delay_seconds,
    )

    pipeline.run()

    db_pool.close_all()
    logger.info("Pipeline complete")


if __name__ == "__main__":
    main()
