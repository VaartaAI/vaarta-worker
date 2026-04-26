from __future__ import annotations
from models.article import Article
from models.source import Source
from db.repositories.base_repository import BaseRepository


class ArticleRepository(BaseRepository):

    def exists_by_url(self, url: str) -> bool:
        row = self._execute_one(
            "SELECT 1 FROM articles WHERE url = %s",
            (url,)
        )
        return row is not None

    def save(self, article: Article) -> Article:
        row = self._execute_one(
            """
            INSERT INTO articles (source_id, cluster_id, url, title, body_text, published_at, image_url)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                article.source.id,
                article.cluster_id,
                article.url,
                article.title,
                article.body_text,
                article.published_at,
                article.image_url,
            )
        )
        article.id = row["id"]
        return article

    def get_by_cluster(self, cluster_id: int, limit: int = 3) -> list[Article]:
        rows = self._execute(
            """
            SELECT a.*, s.name as source_name, s.domain, s.trust_score, s.political_lean
            FROM articles a
            JOIN sources s ON s.id = a.source_id
            WHERE a.cluster_id = %s
            ORDER BY s.trust_score DESC
            LIMIT %s
            """,
            (cluster_id, limit)
        )
        return [self._row_to_article(r) for r in rows]

    def _row_to_article(self, row: dict) -> Article:
        return Article(
            id=row["id"],
            url=row["url"],
            title=row["title"],
            body_text=row.get("body_text", ""),
            published_at=row.get("published_at"),
            cluster_id=row.get("cluster_id"),
            image_url=row.get("image_url"),
            source=Source(
                name=row["source_name"],
                domain=row["domain"],
                trust_score=row["trust_score"],
                political_lean=row["political_lean"],
            )
        )
