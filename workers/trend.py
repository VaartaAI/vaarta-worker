"""
Trend worker — one-shot.

Recomputes the importance score for every cluster created in the last 48h.

    score = log(article_count + 1) * category_weight * e^(-age_hours / 24)

Half-life ≈ 17 hours. Reads cluster.category which the LLM worker has
filled in; clusters not yet summarized fall back to the default weight.
"""
from __future__ import annotations
import os
import math
import datetime

from dotenv import load_dotenv
load_dotenv()

from infra.logging_config import configure_logging  # noqa: E402
configure_logging(level=os.getenv("LOG_LEVEL", "INFO"))

import structlog  # noqa: E402

from config.settings import Settings  # noqa: E402
from db.connection import DatabasePool  # noqa: E402
from db.repositories.cluster_repository import ClusterRepository  # noqa: E402

logger = structlog.get_logger(__name__)

CATEGORY_WEIGHTS: dict[str, float] = {
    "politics":      1.4,
    "business":      1.2,
    "tech":          1.1,
    "health":        1.1,
    "science":       1.0,
    "general":       1.0,
    "sports":        0.9,
    "entertainment": 0.8,
}


def _score(article_count: int, category: str | None, age_hours: float) -> float:
    weight = CATEGORY_WEIGHTS.get(category or "general", 1.0)
    decay = math.exp(-max(age_hours, 0) / 24.0)
    return round(math.log(article_count + 1) * weight * decay, 4)


def run() -> None:
    settings = Settings.from_env()
    log = logger.bind(worker="trend")

    pool = DatabasePool(settings)
    repo = ClusterRepository(pool)

    now = datetime.datetime.utcnow()
    try:
        clusters = repo.get_hot_clusters(lookback_hours=48, min_articles=1)
    except Exception as exc:
        log.error("fetch_clusters_failed", error=str(exc))
        pool.close_all()
        return

    updates = 0
    for cluster in clusters:
        try:
            created = cluster.created_at
            if created.tzinfo is not None:
                created = created.replace(tzinfo=None)
            age_h = (now - created).total_seconds() / 3600.0
            score = _score(cluster.article_count, cluster.category, age_h)
            repo.update_importance_score(cluster.id, score)
            updates += 1
        except Exception as exc:
            log.error("score_failed", cluster_id=cluster.id, error=str(exc))

    log.info("trend_complete", clusters_scored=updates)
    pool.close_all()


if __name__ == "__main__":
    run()
