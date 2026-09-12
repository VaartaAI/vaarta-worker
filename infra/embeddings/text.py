"""Build the text that gets embedded for an article."""
from __future__ import annotations
import html
import re

from models.article import Article

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def clean_html(raw: str | None) -> str:
    """Strip tags and entities from a feed body; collapse whitespace."""
    if not raw:
        return ""
    return _WS.sub(" ", html.unescape(_TAG.sub(" ", raw))).strip()


def embedding_text(article: Article, body_chars: int) -> str:
    """
    Title plus a short body excerpt. The excerpt disambiguates headlines that
    repeat across days ("Sensex jumps 500 points") and helps when two papers
    lead with different angles on the same event.
    """
    title = (article.title or "").strip()
    body = clean_html(article.body_text)[:body_chars].strip()
    return f"{title}. {body}" if body else title
