from __future__ import annotations
from models.cluster import ArticleCluster
from db.repositories.base_repository import BaseRepository


class ClusterRepository(BaseRepository):

    def find_similar(
        self,
        title: str,
        category: str,
        threshold: float,
        lookback_hours: int
    ) -> ArticleCluster | None:
        row = self._execute_one(
            """
            SELECT ac.id, ac.category, ac.article_count, ac.importance_score, ac.created_at,
                   MAX(similarity(a.title, %s)) as sim
            FROM article_clusters ac
            JOIN articles a ON a.cluster_id = ac.id
            WHERE ac.created_at > NOW() - (%s * INTERVAL '1 hour')
              AND ac.category = %s
            GROUP BY ac.id
            HAVING MAX(similarity(a.title, %s)) > %s
            ORDER BY sim DESC
            LIMIT 1
            """,
            (title, lookback_hours, category, title, threshold)
        )
        return self._row_to_cluster(row) if row else None

    def create(self, cluster: ArticleCluster) -> ArticleCluster:
        row = self._execute_one(
            """
            INSERT INTO article_clusters (category, article_count, importance_score)
            VALUES (%s, %s, %s)
            RETURNING *
            """,
            (cluster.category, cluster.article_count, cluster.importance_score)
        )
        cluster.id = row["id"]
        cluster.created_at = row["created_at"]
        return cluster

    def increment_count(self, cluster_id: int):
        self._execute(
            """
            UPDATE article_clusters
            SET article_count = article_count + 1, updated_at = NOW()
            WHERE id = %s
            """,
            (cluster_id,)
        )

    def _row_to_cluster(self, row: dict) -> ArticleCluster:
        return ArticleCluster(
            id=row["id"],
            category=row["category"],
            article_count=row["article_count"],
            importance_score=row.get("importance_score", 0.0),
            created_at=row.get("created_at"),
        )
