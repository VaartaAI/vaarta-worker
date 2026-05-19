"""
Queue interface — the contract every queue implementation must satisfy.

The producer (ingest worker) only needs `enqueue()`. The consumer (llm worker)
needs the rest. Workers depend on this interface, not on any concrete impl,
so swapping Postgres for Redis/SQS is a one-line change at the composition
root.
"""
from __future__ import annotations
from abc import ABC, abstractmethod


class Queue(ABC):
    """FIFO job queue with at-least-once delivery semantics."""

    @abstractmethod
    def enqueue(self, cluster_id: int) -> None:
        """Add a cluster to the queue. Idempotent — safe to call twice."""
        raise NotImplementedError

    @abstractmethod
    def claim_one(self, max_attempts: int = 5) -> int | None:
        """
        Atomically claim the oldest pending cluster, marking it in-progress.
        Skips rows whose attempts >= max_attempts.
        Returns the cluster_id, or None if nothing actionable.
        """
        raise NotImplementedError

    @abstractmethod
    def mark_done(self, cluster_id: int) -> None:
        """Mark a claimed cluster as successfully processed."""
        raise NotImplementedError

    @abstractmethod
    def mark_failed(self, cluster_id: int, error: str) -> None:
        """Mark a claimed cluster as permanently failed (won't be retried)."""
        raise NotImplementedError

    @abstractmethod
    def release(self, cluster_id: int) -> None:
        """Return a claimed cluster to pending — for transient failures."""
        raise NotImplementedError

    @abstractmethod
    def release_stale(self, stuck_minutes: int = 30) -> int:
        """Reset in_progress rows whose worker died. Returns count released."""
        raise NotImplementedError

    @abstractmethod
    def sweep_exhausted(self, max_attempts: int = 5) -> int:
        """Promote pending rows that exceeded their retry budget to 'failed'. Returns count."""
        raise NotImplementedError
