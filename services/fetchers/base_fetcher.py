from __future__ import annotations
from abc import ABC, abstractmethod
from models.article import Article


class NewsFetcher(ABC):
    """
    Abstract base for all news sources.
    Add RSSFetcher, GNewsFetcher etc. later
    without touching the pipeline.
    """

    @abstractmethod
    def fetch(self, category: str) -> list[Article]:
        """Fetch articles for a given category. Returns list of Article objects."""
        pass

    @abstractmethod
    def supported_categories(self) -> list[str]:
        """Returns list of category names this fetcher supports."""
        pass
