import time
from services.fetchers.base_fetcher import NewsFetcher
from services.clustering_service import ClusteringService
from services.summarization_service import SummarizationService
from db.repositories.article_repository import ArticleRepository
from db.repositories.source_repository import SourceRepository
from db.repositories.summary_repository import SummaryRepository


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
            print(f"\n[Pipeline] Fetching: {category}")
            articles = self._fetcher.fetch(category)
            print(f"  Fetched {len(articles)} articles")

            for article in articles:
                # Step 1: Skip if already ingested
                if self._article_repo.exists_by_url(article.url):
                    continue

                # Step 2: Resolve source (find existing or create new)
                article.source = self._source_repo.find_or_create(article.source)

                # Step 3: Find matching cluster or create new one
                cluster, is_new = self._clustering_service.find_or_create_cluster(
                    article, category
                )
                article.cluster_id = cluster.id

                # Step 4: Save article to DB
                self._article_repo.save(article)
                print(f"  {'[NEW CLUSTER]' if is_new else '[ADDED TO]'} #{cluster.id}: {article.title[:70]}")

                if is_new:
                    new_cluster_ids.append(cluster.id)

        # Step 5: Summarize all new clusters with rate limiting
        print(f"\n[Pipeline] Summarizing {len(new_cluster_ids)} new clusters...")
        for i, cluster_id in enumerate(new_cluster_ids):
            summary = self._summarization_service.summarize(cluster_id)
            if summary:
                self._summary_repo.save(summary)
                print(f"  [SUMMARIZED] cluster #{cluster_id}")
            else:
                print(f"  [FAILED] cluster #{cluster_id}")
            # Rate limit: stay under 15 requests/min on free tier
            if i < len(new_cluster_ids) - 1:
                time.sleep(self._summarization_delay)

        print(f"\n[Pipeline] Done. {len(new_cluster_ids)} new clusters created and summarized.")
