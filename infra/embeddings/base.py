from __future__ import annotations
from abc import ABC, abstractmethod


class EmbeddingError(Exception):
    """The embedding provider failed; callers should fall back, not crash."""


class EmbeddingQuotaExhausted(EmbeddingError):
    """
    A per-day quota is spent. Retrying is pointless until the reset (and every
    rejected retry counts against the quota too). Callers should stop asking
    for embeddings for the rest of the run.
    """


class EmbeddingClient(ABC):
    """Turns a batch of texts into one vector each, same order, same length."""

    name: str
    dimensions: int

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError
