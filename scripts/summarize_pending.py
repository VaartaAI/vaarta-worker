"""
One-time script to summarize clusters that failed previously.
Runs through all clusters with no summary and processes them.
"""
import time
from config.settings import Settings
from db.connection import DatabasePool
from db.repositories.article_repository import ArticleRepository
from db.repositories.summary_repository import SummaryRepository
from db.repositories.base_repository import BaseRepository
from services.summarization_service import SummarizationService


class ClusterWithoutSummaryRepo(BaseRepository):
    def get_pending(self) -> list:
        return self._execute(
            """
            SELECT ac.id FROM article_clusters ac
            LEFT JOIN summaries s ON s.cluster_id = ac.id
            WHERE s.id IS NULL
            ORDER BY ac.id ASC
            """
        )


def main():
    settings = Settings.from_env()
    db_pool = DatabasePool(settings)

    article_repo     = ArticleRepository(db_pool)
    summary_repo     = SummaryRepository(db_pool)
    pending_repo     = ClusterWithoutSummaryRepo(db_pool)
    summarization_svc = SummarizationService(article_repo, settings)

    pending = pending_repo.get_pending()
    print(f"Found {len(pending)} clusters without summaries.\n")

    for i, row in enumerate(pending):
        cluster_id = row["id"]
        print(f"[{i+1}/{len(pending)}] Summarizing cluster #{cluster_id}...")
        summary = summarization_svc.summarize(cluster_id)
        if summary:
            summary_repo.save(summary)
            print(f"  ✓ Done: {summary.summary_text[:80]}")
        else:
            print(f"  ✗ Failed")

        if i < len(pending) - 1:
            time.sleep(settings.summarization_delay_seconds)

    print("\nAll done!")
    db_pool.close_all()


if __name__ == "__main__":
    main()
