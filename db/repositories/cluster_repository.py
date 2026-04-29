from __future__ import annotations
from models.cluster import ArticleCluster
from db.repositories.base_repository import BaseRepository


class ClusterRepository(BaseRepository):

    def find_similar(
        self,
        title: str,
        threshold: float,
        lookback_hours: int,
    ) -> ArticleCluster | None:
        """
        Find the closest existing cluster within the lookback window using
        title trigram similarity. Category is intentionally not part of the
        match — the LLM owns categorization, and pre-LLM categories are too
        unreliable to scope clustering by.
        """
        row = self._execute_one(
            """
            SELECT ac.id, ac.category, ac.article_count, ac.importance_score, ac.created_at,
                   MAX(similarity(a.title, %s)) as sim
            FROM article_clusters ac
            JOIN articles a ON a.cluster_id = ac.id
            WHERE ac.created_at > NOW() - (%s * INTERVAL '1 hour')
            GROUP BY ac.id
            HAVING MAX(similarity(a.title, %s)) > %s
            ORDER BY sim DESC
            LIMIT 1
            """,
            (title, lookback_hours, title, threshold),
        )
        return self._row_to_cluster(row) if row else None

    def create(self, cluster: ArticleCluster) -> ArticleCluster:
        """Create a cluster. category is typically NULL at creation time."""
        row = self._execute_one(
            """
            INSERT INTO article_clusters (category, article_count, importance_score)
            VALUES (%s, %s, %s)
            RETURNING *
            """,
            (cluster.category, cluster.article_count, cluster.importance_score),
        )
        cluster.id = row["id"]
        cluster.created_at = row["created_at"]
        return cluster

    def increment_count(self, cluster_id: int) -> None:
        self._execute(
            """
            UPDATE article_clusters
            SET article_count = article_count + 1, updated_at = NOW()
            WHERE id = %s
            """,
            (cluster_id,),
        )

    def update_category(self, cluster_id: int, category: str) -> None:
        """Called by the LLM worker after summarization to set the authoritative category."""
        self._execute(
            """
            UPDATE article_clusters
            SET category = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (category, cluster_id),
        )

    def get_hot_clusters(
        self,
        lookback_hours: int = 48,
        min_articles: int = 1,
    ) -> list[ArticleCluster]:
        """Return clusters created within the lookback window, ordered by article count."""
        rows = self._execute(
            """
            SELECT id, category, article_count, importance_score, created_at
            FROM article_clusters
            WHERE created_at > NOW() - (%s * INTERVAL '1 hour')
              AND article_count >= %s
            ORDER BY article_count DESC
            """,
            (lookback_hours, min_articles),
        )
        return [self._row_to_cluster(row) for row in rows]

    def update_importance_score(self, cluster_id: int, score: float) -> None:
        self._execute(
            """
            UPDATE article_clusters
            SET importance_score = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (score, cluster_id),
        )

    @staticmethod
    def _row_to_cluster(row: dict) -> ArticleCluster:
        return ArticleCluster(
            id=row["id"],
            category=row.get("category"),
            article_count=row["article_count"],
            importance_score=row.get("importance_score", 0.0),
            created_at=row.get("created_at"),
        )
