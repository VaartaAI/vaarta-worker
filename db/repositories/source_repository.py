from __future__ import annotations
from models.source import Source
from db.repositories.base_repository import BaseRepository


class SourceRepository(BaseRepository):

    def find_by_domain(self, domain: str) -> Source | None:
        row = self._execute_one(
            "SELECT * FROM sources WHERE domain = %s",
            (domain,)
        )
        return self._row_to_source(row) if row else None

    def create(self, source: Source) -> Source:
        row = self._execute_one(
            """
            INSERT INTO sources (name, domain, trust_score, political_lean)
            VALUES (%s, %s, %s, %s)
            RETURNING *
            """,
            (source.name, source.domain, source.trust_score, source.political_lean)
        )
        source.id = row["id"]
        return source

    def find_or_create(self, source: Source) -> Source:
        existing = self.find_by_domain(source.domain)
        return existing if existing else self.create(source)

    def _row_to_source(self, row: dict) -> Source:
        return Source(
            id=row["id"],
            name=row["name"],
            domain=row["domain"],
            trust_score=row["trust_score"],
            political_lean=row["political_lean"],
        )
