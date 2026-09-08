from __future__ import annotations
from datetime import datetime
from typing import Optional

from db.repositories.base_repository import BaseRepository
from models.source_state import SourceState


class SourceStateRepository(BaseRepository):
    """
    Tiny key-value table keyed by source_key (e.g. 'rss:The Hindu',
    'gnews:business'). Sources read their cursor at the start of fetch()
    and write it back after a successful call.
    """

    def get(self, source_key: str) -> Optional[SourceState]:
        row = self._execute_one(
            """
            SELECT source_key, last_fetched_at, last_etag, last_modified
            FROM source_state WHERE source_key = %s
            """,
            (source_key,),
        )
        if not row:
            return None
        return SourceState(
            source_key=row["source_key"],
            last_fetched_at=row["last_fetched_at"],
            last_etag=row["last_etag"],
            last_modified=row["last_modified"],
        )

    def upsert(
        self,
        source_key: str,
        last_fetched_at: Optional[datetime] = None,
        last_etag: Optional[str] = None,
        last_modified: Optional[str] = None,
    ) -> None:
        # COALESCE preserves untouched fields so callers can write subsets
        # (RSS only updates etag/modified; cursor-based sources only update last_fetched_at).
        self._execute(
            """
            INSERT INTO source_state (source_key, last_fetched_at, last_etag, last_modified, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (source_key) DO UPDATE SET
                last_fetched_at = COALESCE(EXCLUDED.last_fetched_at, source_state.last_fetched_at),
                last_etag       = COALESCE(EXCLUDED.last_etag,       source_state.last_etag),
                last_modified   = COALESCE(EXCLUDED.last_modified,   source_state.last_modified),
                updated_at      = NOW()
            """,
            (source_key, last_fetched_at, last_etag, last_modified),
        )
