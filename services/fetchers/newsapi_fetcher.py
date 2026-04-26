from __future__ import annotations
import httpx
from urllib.parse import urlparse
from datetime import datetime
from models.article import Article
from models.source import Source
from services.fetchers.base_fetcher import NewsFetcher
from config.settings import Settings


# Maps our internal category names to NewsAPI category names
CATEGORY_MAP = {
    "general":       "general",
    "business":      "business",
    "tech":          "technology",
    "sports":        "sports",
    "entertainment": "entertainment",
    "health":        "health",
    "science":       "science",
}


class NewsAPIFetcher(NewsFetcher):

    BASE_URL = "https://newsapi.org/v2/top-headlines"

    def __init__(self, settings: Settings):
        self._api_key = settings.newsapi_key
        self._country = settings.newsapi_country
        self._page_size = settings.newsapi_page_size

    def supported_categories(self) -> list[str]:
        return list(CATEGORY_MAP.keys())

    def fetch(self, category: str) -> list[Article]:
        newsapi_category = CATEGORY_MAP.get(category, "general")
        try:
            response = httpx.get(
                self.BASE_URL,
                params={
                    "country": self._country,
                    "category": newsapi_category,
                    "pageSize": self._page_size,
                    "apiKey": self._api_key,
                },
                timeout=10.0
            )
            response.raise_for_status()
            data = response.json()

            # NewsAPI free tier sometimes blocks country filter — fallback to everything
            if data.get("totalResults", 0) == 0:
                response = httpx.get(
                    self.BASE_URL,
                    params={
                        "category": newsapi_category,
                        "pageSize": self._page_size,
                        "apiKey": self._api_key,
                    },
                    timeout=10.0
                )
                response.raise_for_status()

        except httpx.HTTPError as e:
            print(f"  [NewsAPI] HTTP error for {category}: {e}")
            return []

        articles = []
        for item in response.json().get("articles", []):
            article = self._parse_item(item, category)
            if article:
                articles.append(article)

        return articles

    def _parse_item(self, item: dict, category: str) -> Article | None:
        url   = item.get("url", "").strip()
        title = item.get("title", "").strip()

        # Skip removed or empty articles
        if not url or not title or title == "[Removed]":
            return None

        source_name = item.get("source", {}).get("name") or "Unknown"
        domain      = self._extract_domain(url)
        body        = item.get("content") or item.get("description") or ""
        published   = self._parse_date(item.get("publishedAt"))
        image_url   = item.get("urlToImage") or None

        return Article(
            url=url,
            title=title,
            body_text=body,
            published_at=published,
            image_url=image_url,
            source=Source(name=source_name, domain=domain),
        )

    def _extract_domain(self, url: str) -> str:
        try:
            return urlparse(url).netloc.replace("www.", "")
        except Exception:
            return "unknown"

    def _parse_date(self, date_str: str | None) -> datetime | None:
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except ValueError:
            return None
