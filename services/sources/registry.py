"""
Loads sources.yaml and instantiates the right NewsSource subclass per entry.

Adding a new source = one YAML entry. Adding a new *type* of source =
one new class + one branch in the factory below.
"""
from __future__ import annotations
from pathlib import Path

import yaml

from config.settings import Settings
from db.repositories.source_state_repository import SourceStateRepository
from services.sources.base import NewsSource
from services.sources.rss_source import RSSSource
from services.sources.newsapi_source import NewsAPISource


def build_sources(
    config_path: Path | str,
    settings: Settings,
    state_repo: SourceStateRepository | None = None,
) -> list[NewsSource]:
    path = Path(config_path)
    with path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    sources: list[NewsSource] = []
    for entry in config.get("sources", []) or []:
        kind = entry.get("type")
        if kind == "rss":
            sources.append(RSSSource(
                name=entry["name"],
                url=entry["url"],
                trust_score=int(entry.get("trust_score", 3)),
                state_repo=state_repo,
            ))
        elif kind == "newsapi":
            sources.append(NewsAPISource(
                category=entry["category"],
                api_key=settings.newsapi_key,
                page_size=settings.newsapi_page_size,
                state_repo=state_repo,
            ))
        else:
            raise ValueError(f"Unknown source type in {path}: {kind!r}")

    return sources
