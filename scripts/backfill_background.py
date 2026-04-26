"""
Backfills deep_explainer for summaries that were generated before
the background field was added to the prompt.
"""
import time
from config.settings import Settings
from db.connection import DatabasePool
from db.repositories.article_repository import ArticleRepository
from db.repositories.summary_repository import SummaryRepository
from db.repositories.base_repository import BaseRepository
from services.summarization_service import SummarizationService


class NullBackgroundRepo(BaseRepository):
    def get_cluster_ids(self) -> list:
        return self._execute(
            """
            SELECT cluster_id FROM summaries
            WHERE deep_explainer IS NULL OR deep_explainer = ''
            ORDER BY cluster_id ASC
            """
        )

    def update_background(self, cluster_id: int, background: str):
        self._execute(
            """
            UPDATE summaries SET deep_explainer = %s
            WHERE cluster_id = %s
            """,
            (background, cluster_id)
        )


def main():
    settings = Settings.from_env()
    db_pool = DatabasePool(settings)

    article_repo     = ArticleRepository(db_pool)
    summary_repo     = SummaryRepository(db_pool)
    backfill_repo    = NullBackgroundRepo(db_pool)
    summarization_svc = SummarizationService(article_repo, settings)

    pending = backfill_repo.get_cluster_ids()
    print(f"Found {len(pending)} summaries missing background.\n")

    for i, row in enumerate(pending):
        cluster_id = row["cluster_id"]
        print(f"[{i+1}/{len(pending)}] Processing cluster #{cluster_id}...")

        summary = summarization_svc.summarize(cluster_id)
        if summary and summary.deep_explainer:
            backfill_repo.update_background(cluster_id, summary.deep_explainer)
            print(f"  ✓ {summary.deep_explainer[:100]}")
        else:
            print(f"  ✗ Failed or no background returned")

        if i < len(pending) - 1:
            time.sleep(settings.summarization_delay_seconds)

    print("\nBackfill complete!")
    db_pool.close_all()


if __name__ == "__main__":
    main()
