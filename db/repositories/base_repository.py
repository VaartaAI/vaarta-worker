from __future__ import annotations
from psycopg2.extras import RealDictCursor
from db.connection import DatabasePool


class BaseRepository:
    def __init__(self, db_pool: DatabasePool):
        self._pool = db_pool

    def _execute(self, query: str, params: tuple = None) -> list:
        """Execute a query and return all rows as dicts."""
        conn = self._pool.get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                conn.commit()
                try:
                    return cur.fetchall()
                except Exception:
                    return []
        finally:
            self._pool.release_connection(conn)

    def _execute_one(self, query: str, params: tuple = None) -> dict | None:
        """Execute a query and return a single row."""
        rows = self._execute(query, params)
        return rows[0] if rows else None
