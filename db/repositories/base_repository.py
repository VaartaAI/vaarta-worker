from __future__ import annotations
import logging
from psycopg2 import DatabaseError, InterfaceError, OperationalError
from psycopg2.extras import RealDictCursor
from db.connection import DatabasePool

logger = logging.getLogger(__name__)


class BaseRepository:
    def __init__(self, db_pool: DatabasePool):
        self._pool = db_pool

    def _execute(self, query: str, params: tuple = None) -> list:
        """Execute a query and return all rows as dicts."""
        conn = self._pool.get_connection()
        broken = False
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                conn.commit()
                try:
                    return cur.fetchall()
                except DatabaseError:
                    # Query was not a SELECT (INSERT/UPDATE/DELETE with no RETURNING)
                    return []
        except (OperationalError, InterfaceError) as e:
            # Socket-level failure (timeout, server closed the connection). The
            # connection is unusable: don't attempt a rollback on it, and make
            # sure the pool closes it instead of handing it to the next caller.
            broken = True
            logger.error("Database connection error: %s | query: %s", e, query)
            raise
        except DatabaseError as e:
            try:
                conn.rollback()
            except (OperationalError, InterfaceError):
                broken = True
            logger.error("Database error executing query: %s | params: %s | error: %s", query, params, e)
            raise
        finally:
            self._pool.release_connection(conn, broken=broken)

    def _execute_one(self, query: str, params: tuple = None) -> dict | None:
        """Execute a query and return a single row."""
        rows = self._execute(query, params)
        return rows[0] if rows else None
