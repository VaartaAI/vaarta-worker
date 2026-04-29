"""
Uniform interface for all news sources (RSS, NewsAPI, GNews, …).

A NewsSource encapsulates *everything* about an origin: its URL, its
auth, and its conversion of raw items into Article objects. The
ingestion worker just iterates over a list of sources and calls fetch().
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Iterable

from models.article import Article


class NewsSource(ABC):
    """One origin of articles."""

    name: str  # human-readable identifier used in logs and metrics

    @abstractmethod
    def fetch(self) -> Iterable[Article]:
        """Yield Article objects. Implementations should not raise on empty/bad data — log and yield nothing."""
        raise NotImplementedError
