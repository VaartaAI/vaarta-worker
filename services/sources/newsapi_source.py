"""
NewsAPI source. One instance per category.

Uses /v2/everything with `from=last_fetched_at` so each call only returns
articles published since the previous successful fetch. The cursor is
persisted via SourceStateRepository, so quota isn't burned re-fetching the
same headlines on every cron tick.

/everything doesn't accept the `category` parameter that /top-headlines does,
so categories are mapped to keyword queries below.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Iterable
from urllib.parse import urlparse

import httpx
import structlog

from models.article import Article
from models.source import Source
from services.sources.base import NewsSource
from db.repositories.source_state_repository import SourceStateRepository

logger = structlog.get_logger(__name__)


# /everything doesn't have category buckets; translate to a focused query.
CATEGORY_QUERIES = {
    "general":       "india",
    "politics":      "india AND (politics OR government OR election OR parliament)",
    "business":      "india AND (business OR economy OR market OR finance)",
    "tech":          "india AND (technology OR startup OR software OR AI)",
    "sports":        "india AND (sports OR cricket OR olympics)",
    "entertainment": "india AND (entertainment OR bollywood OR films)",
    "health":        "india AND (health OR medicine OR healthcare)",
    "science":       "india AND (science OR research OR space)",
}

# First-run window: don't pull a month of history when there's no cursor yet.
FIRST_RUN_LOOKBACK = timedelta(hours=24)


class NewsAPISource(NewsSource):

    BASE_URL = "https://newsapi.org/v2/everything"

    def __init__(
        self,
        category: str,
        api_key: str,
        page_size: int = 20,
        state_repo: SourceStateRepository | None = None,
    ):
        self.name = f"newsapi:{category}"
        self._category = category
        self._api_key = api_key
        self._page_size = page_size
        self._state_repo = state_repo
        self._state_key = self.name

    def fetch(self) -> Iterable[Article]:
        log = logger.bind(source=self.name)

        from_dt: datetime | None = None
        if self._state_repo is not None:
            state = self._state_repo.get(self._state_key)
            if state and state.last_fetched_at:
                from_dt = state.last_fetched_at
        if from_dt is None:
            from_dt = datetime.now(timezone.utc) - FIRST_RUN_LOOKBACK

        # Capture the cursor BEFORE the call so the next fetch covers anything
        # published while this call was in flight. URL dedup absorbs any overlap.
        fetch_started_at = datetime.now(timezone.utc)

        params = {
            "q": CATEGORY_QUERIES.get(self._category, f"india {self._category}"),
            "from": from_dt.isoformat(),
            "sortBy": "publishedAt",
            "language": "en",
            "pageSize": self._page_size,
            "apiKey": self._api_key,
        }
        try:
            data = self._get(params)
        except httpx.HTTPError as exc:
            log.error("newsapi_http_error", error=str(exc))
            return

        for item in data.get("articles", []) or []:
            article = self._parse_item(item)
            if article:
                yield article

        # Only advance the cursor on a successful call. On failure we leave it
        # alone so the next run re-tries the same window.
        if self._state_repo is not None:
            self._state_repo.upsert(
                self._state_key,
                last_fetched_at=fetch_started_at,
            )

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
