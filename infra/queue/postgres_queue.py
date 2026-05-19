"""
Postgres-backed implementation of the Queue interface.

Uses the `summarization_queue` table and SELECT ... FOR UPDATE SKIP LOCKED
for atomic, multi-worker-safe claims. Multiple instances of the LLM worker
can run concurrently against the same table without claim collisions.
"""
from __future__ import annotations

from db.repositories.base_repository import BaseRepository
from infra.queue.base import Queue


class PostgresQueue(BaseRepository, Queue):
    """Queue backed by the summarization_queue Postgres table."""

    def enqueue(self, cluster_id: int) -> None:
        self._execute(
            """
            INSERT INTO summarization_queue (cluster_id)
            VALUES (%s)
            ON CONFLICT (cluster_id) DO NOTHING
            """,
            (cluster_id,),
        )

    def claim_one(self, max_attempts: int = 5) -> int | None:
        row = self._execute_one(
            """
            UPDATE summarization_queue
            SET status      = 'in_progress',
                locked_at   = NOW(),
                attempts    = attempts + 1
            WHERE cluster_id = (
                SELECT cluster_id
                FROM summarization_queue
                WHERE status = 'pending'
                  AND attempts < %s
                ORDER BY enqueued_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING cluster_id
            """,
            (max_attempts,),
        )
        return row["cluster_id"] if row else None

    def mark_done(self, cluster_id: int) -> None:
        self._execute(
            "UPDATE summarization_queue SET status = 'done' WHERE cluster_id = %s",
            (cluster_id,),
        )

    def mark_failed(self, cluster_id: int, error: str) -> None:
        self._execute(
            """
            UPDATE summarization_queue
            SET status = 'failed', last_error = %s
            WHERE cluster_id = %s
            """,
            (error[:500], cluster_id),
        )

    def release(self, cluster_id: int) -> None:
        self._execute(
            """
            UPDATE summarization_queue
            SET status = 'pending', locked_at = NULL
            WHERE cluster_id = %s
            """,
            (cluster_id,),
        )

    def release_stale(self, stuck_minutes: int = 30) -> int:
        rows = self._execute(
            """
            UPDATE summarization_queue
            SET status = 'pending', locked_at = NULL
            WHERE status = 'in_progress'
              AND locked_at < NOW() - (%s * INTERVAL '1 minute')
            RETURNING cluster_id
            """,
            (stuck_minutes,),
        )
        return len(rows)

    def sweep_exhausted(self, max_attempts: int = 5) -> int:
        rows = self._execute(
            """
            UPDATE summarization_queue
            SET status = 'failed',
                last_error = COALESCE(last_error, '') || ' [max_attempts_exceeded]'
            WHERE status = 'pending'
              AND attempts >= %s
            RETURNING cluster_id
            """,
            (max_attempts,),
        )
        return len(rows)
