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


def main():
    print("[VaartaAI] Starting ingestion pipeline...\n")

    # 1. Load config from .env
    settings = Settings.from_env()

    # 2. DB connection pool (singleton)
    db_pool = DatabasePool(settings)

    # 3. Repositories
    article_repo = ArticleRepository(db_pool)
    cluster_repo = ClusterRepository(db_pool)
    source_repo  = SourceRepository(db_pool)
    summary_repo = SummaryRepository(db_pool)

    # 4. Services
    fetcher               = NewsAPIFetcher(settings)
    clustering_service    = ClusteringService(cluster_repo, settings)
    summarization_service = SummarizationService(article_repo, settings)

    # 5. Wire up and run pipeline
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

    # 6. Clean up DB connections
    db_pool.close_all()
    print("\n[VaartaAI] Pipeline complete.")


if __name__ == "__main__":
    main()
