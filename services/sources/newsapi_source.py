"""
NewsAPI source. One instance per category — sources.yaml has one entry
per category you want fetched.
"""
from __future__ import annotations
from datetime import datetime
from typing import Iterable
from urllib.parse import urlparse

import httpx
import structlog

from models.article import Article
from models.source import Source
from services.sources.base import NewsSource

logger = structlog.get_logger(__name__)


# Internal category names → NewsAPI category names
CATEGORY_MAP = {
    "general":       "general",
    "business":      "business",
    "tech":          "technology",
    "sports":        "sports",
    "entertainment": "entertainment",
    "health":        "health",
    "science":       "science",
}


class NewsAPISource(NewsSource):

    BASE_URL = "https://newsapi.org/v2/top-headlines"

    def __init__(
        self,
        category: str,
        api_key: str,
        country: str = "in",
        page_size: int = 20,
    ):
        self.name = f"newsapi:{category}"
        self._category = category
        self._api_key = api_key
        self._country = country
        self._page_size = page_size

    def fetch(self) -> Iterable[Article]:
        log = logger.bind(source=self.name)
        params = {
            "country": self._country,
            "category": CATEGORY_MAP.get(self._category, "general"),
            "pageSize": self._page_size,
            "apiKey": self._api_key,
        }
        try:
            data = self._get(params)
            if data.get("totalResults", 0) == 0:
                # NewsAPI free tier sometimes blocks the country filter
                params.pop("country", None)
                data = self._get(params)
        except httpx.HTTPError as exc:
            log.error("newsapi_http_error", error=str(exc))
            return

        for item in data.get("articles", []) or []:
            article = self._parse_item(item)
            if article:
                yield article

    def _get(self, params: dict) -> dict:
        response = httpx.get(self.BASE_URL, params=params, timeout=10.0)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _parse_item(item: dict) -> Article | None:
        url = (item.get("url") or "").strip()
        title = (item.get("title") or "").strip()
        if not url or not title or title == "[Removed]":
            return None

        source_name = (item.get("source") or {}).get("name") or "Unknown"
        domain = urlparse(url).netloc.replace("www.", "") or "unknown"
        body = item.get("content") or item.get("description") or ""
        published = NewsAPISource._parse_date(item.get("publishedAt"))
        image = item.get("urlToImage") or None

        return Article(
            url=url,
            title=title,
            body_text=body,
            published_at=published,
            image_url=image,
            source=Source(name=source_name, domain=domain),
        )

    @staticmethod
    def _parse_date(s: str | None) -> datetime | None:
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
