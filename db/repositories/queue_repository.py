"""
Postgres-backed FIFO queue between ingestion and the LLM worker.

Ingestion enqueues cluster ids; LLM workers claim them with
SELECT ... FOR UPDATE SKIP LOCKED so multiple workers can run concurrently
without ever picking the same row.
"""
from __future__ import annotations
from db.repositories.base_repository import BaseRepository


class QueueRepository(BaseRepository):

    def enqueue(self, cluster_id: int) -> None:
        """Mark a cluster as needing summarization. No-op if already queued."""
        self._execute(
            """
            INSERT INTO summarization_queue (cluster_id)
            VALUES (%s)
            ON CONFLICT (cluster_id) DO NOTHING
            """,
            (cluster_id,),
        )

    def claim_one(self, max_attempts: int = 5) -> int | None:
        """
        Atomically pop one pending cluster, marking it in_progress.
        Skips rows whose attempts counter has already reached max_attempts —
        those need to be promoted to 'failed' by sweep_exhausted().
        Returns the cluster id, or None if the queue has nothing actionable.
        """
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
        """Return a claimed job to pending — for transient failures (daily quota, etc.)."""
        self._execute(
            """
            UPDATE summarization_queue
            SET status = 'pending', locked_at = NULL
            WHERE cluster_id = %s
            """,
            (cluster_id,),
        )

    def release_stale(self, stuck_minutes: int = 30) -> int:
        """
        Reset in_progress rows whose worker died mid-run.
        Call periodically from the LLM worker. Returns how many were released.
        """
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
        """
        Promote pending rows that have already burned their retry budget to 'failed'.
        Returns how many were swept.
        """
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
