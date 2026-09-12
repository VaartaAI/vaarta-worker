from __future__ import annotations
from models.article import Article
from models.source import Source
from db.repositories.base_repository import BaseRepository
from db.vector import to_pgvector


class ArticleRepository(BaseRepository):

    def exists_by_url(self, url: str) -> bool:
        row = self._execute_one(
            "SELECT 1 FROM articles WHERE url = %s",
            (url,)
        )
        return row is not None

    def existing_urls(self, urls: list[str]) -> set[str]:
        """
        Return the subset of `urls` already present in articles.url.
        One round trip instead of one per URL; on a remote database that is
        the difference between ~1 and ~50 network round trips per feed.
        """
        if not urls:
            return set()
        rows = self._execute(
            "SELECT url FROM articles WHERE url = ANY(%s)",
            (list(set(urls)),),
        )
        return {r["url"] for r in rows}

    def save(self, article: Article) -> Article:
        row = self._execute_one(
            """
            INSERT INTO articles (source_id, cluster_id, url, title, body_text, published_at, image_url, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector)
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
                to_pgvector(article.embedding),
            )
        )
        article.id = row["id"]
        return article

    def missing_embedding(self, since_hours: int, limit: int = 1000) -> list[dict]:
        """Recent rows with no embedding yet: id, title, body_text. For backfill."""
        return self._execute(
            """
            SELECT id, title, body_text FROM articles
            WHERE embedding IS NULL
              AND fetched_at > NOW() - (%s * INTERVAL '1 hour')
            ORDER BY id
            LIMIT %s
            """,
            (since_hours, limit),
        )

    def set_embeddings(self, items: list[tuple[int, list[float]]]) -> int:
        """Bulk UPDATE articles.embedding from (id, vector) pairs in one statement."""
        if not items:
            return 0
        rows = self._execute(
            """
            UPDATE articles AS a
            SET embedding = v.emb::vector
            FROM (SELECT unnest(%s::int[]) AS id, unnest(%s::text[]) AS emb) AS v
            WHERE a.id = v.id
            RETURNING a.id
            """,
            ([i for i, _ in items], [to_pgvector(e) for _, e in items]),
        )
        return len(rows)

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
