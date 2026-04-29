"""
RSS / Atom feed source using feedparser.

One instance = one feed URL. Add as many entries to sources.yaml as you need;
the registry instantiates one RSSSource per entry.
"""
from __future__ import annotations
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable
from urllib.parse import urlparse

import feedparser
import structlog

from models.article import Article
from models.source import Source
from services.sources.base import NewsSource

logger = structlog.get_logger(__name__)


class RSSSource(NewsSource):

    def __init__(self, name: str, url: str, trust_score: int = 3):
        self.name = name
        self._url = url
        self._trust_score = trust_score

    def fetch(self) -> Iterable[Article]:
        log = logger.bind(source=self.name, url=self._url)
        try:
            feed = feedparser.parse(self._url)
        except Exception as exc:
            log.error("rss_parse_failed", error=str(exc))
            return

        if feed.bozo and not feed.entries:
            log.warning("rss_malformed", error=str(feed.bozo_exception))
            return

        for entry in feed.entries:
            article = self._to_article(entry)
            if article:
                yield article

    def _to_article(self, entry) -> Article | None:
        url = (entry.get("link") or "").strip()
        title = (entry.get("title") or "").strip()
        if not url or not title:
            return None

        body = self._extract_body(entry)
        published = self._parse_date(entry)
        image = self._extract_image(entry)
        domain = urlparse(url).netloc.replace("www.", "") or "unknown"

        return Article(
            url=url,
            title=title,
            body_text=body,
            published_at=published,
            image_url=image,
            source=Source(
                name=self.name,
                domain=domain,
                trust_score=self._trust_score,
            ),
        )

    @staticmethod
    def _extract_body(entry) -> str:
        if entry.get("content"):
            try:
                return entry.content[0].get("value") or ""
            except (IndexError, AttributeError):
                pass
        return entry.get("summary") or entry.get("description") or ""

    @staticmethod
    def _parse_date(entry) -> datetime | None:
        for field in ("published", "updated", "pubDate"):
            value = entry.get(field)
            if value:
                try:
                    return parsedate_to_datetime(value)
                except (TypeError, ValueError):
                    pass
        for field in ("published_parsed", "updated_parsed"):
            value = entry.get(field)
            if value:
                try:
                    return datetime(*value[:6], tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    pass
        return None

    @staticmethod
    def _extract_image(entry) -> str | None:
        media = entry.get("media_content") or []
        for m in media:
            if m.get("url"):
                return m["url"]
        thumbs = entry.get("media_thumbnail") or []
        if thumbs and thumbs[0].get("url"):
            return thumbs[0]["url"]
        for link in entry.get("links", []) or []:
            if link.get("rel") == "enclosure" and "image" in (link.get("type") or ""):
                return link.get("href")
        return None
