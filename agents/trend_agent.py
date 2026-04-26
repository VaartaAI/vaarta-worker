"""
TrendAgent — LangGraph node that scores every cluster from the past 48 hours
with a recency-weighted importance score and persists it to the DB.

Score formula:
    score = log(article_count + 1) * category_weight * e^(-age_hours / 24)

This gives a half-life of ~17 hours, so a cluster 24h old retains ~37% of its
peak score regardless of how many articles it has.
"""
from __future__ import annotations
import math
import datetime
import structlog

from db.repositories.cluster_repository import ClusterRepository
from agents.state import PipelineState

logger = structlog.get_logger(__name__)

# Multipliers reflect editorial newsworthiness of each category.
_CATEGORY_WEIGHTS: dict[str, float] = {
    "politics":      1.4,
    "business":      1.2,
    "tech":          1.1,
    "health":        1.1,
    "science":       1.0,
    "general":       1.0,
    "sports":        0.9,
    "entertainment": 0.8,
}


def _compute_score(article_count: int, category: str, age_hours: float) -> float:
    weight = _CATEGORY_WEIGHTS.get(category, 1.0)
    decay = math.exp(-max(age_hours, 0) / 24.0)
    return round(math.log(article_count + 1) * weight * decay, 4)


class TrendAgent:

    def __init__(self, cluster_repo: ClusterRepository) -> None:
        self._cluster_repo = cluster_repo

    def __call__(self, state: PipelineState) -> dict:
        log = logger.bind(run_id=state["run_id"], agent="trend")
        now = datetime.datetime.utcnow()

        try:
            clusters = self._cluster_repo.get_hot_clusters(lookback_hours=48, min_articles=1)
        except Exception as exc:
            log.error("fetch_clusters_failed", error=str(exc))
            return {"trend_updates": 0, "phase": "done"}

        updates = 0
        for cluster in clusters:
            try:
                created = cluster.created_at
                # Strip timezone info for arithmetic (DB stores UTC naive)
                if created.tzinfo is not None:
                    created = created.replace(tzinfo=None)
                age_hours = (now - created).total_seconds() / 3600.0
                score = _compute_score(cluster.article_count, cluster.category, age_hours)
                self._cluster_repo.update_importance_score(cluster.id, score)
                updates += 1
            except Exception as exc:
                log.error("score_update_failed", cluster_id=cluster.id, error=str(exc))

        log.info("trend_done", clusters_scored=updates)
        return {"trend_updates": updates, "phase": "done"}
