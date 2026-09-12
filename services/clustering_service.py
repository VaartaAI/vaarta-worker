from __future__ import annotations
import structlog

from config.settings import Settings
from db.repositories.cluster_repository import ClusterRepository
from infra import metrics as m
from models.article import Article
from models.cluster import ArticleCluster

logger = structlog.get_logger(__name__)


class ClusteringService:
    """
    Groups same-event articles into clusters.

    Two matching strategies, tried in order:

    1. Semantic — if the article carries an embedding, find the nearest recent
       embedded article by cosine similarity and join its cluster when
           cosine >= cluster_embedding_threshold, or
           cosine >= cluster_hybrid_embedding_threshold and the trigram
           similarity of the two titles >= cluster_hybrid_trigram_threshold.
       The hybrid rule admits slightly weaker semantic matches when the
       headlines also share surface text, and rejects "same topic, different
       event" pairs that embeddings alone tend to score highly.
    2. Trigram — pg_trgm title similarity above cluster_similarity_threshold.
       Used when the article has no embedding (API down, feature disabled) or
       when no embedded neighbour exists yet in the lookback window.

    Clustering is category-blind: the LLM owns categorisation later.
    """

    def __init__(self, cluster_repo: ClusterRepository, settings: Settings):
        self._repo = cluster_repo
        self._lookback_hours = settings.cluster_lookback_hours
        self._trigram_threshold = settings.cluster_similarity_threshold
        self._cosine_threshold = settings.cluster_embedding_threshold
        self._hybrid_cosine = settings.cluster_hybrid_embedding_threshold
        self._hybrid_trigram = settings.cluster_hybrid_trigram_threshold

    def find_or_create_cluster(self, article: Article) -> tuple[ArticleCluster, bool]:
        """Returns (cluster, is_new). is_new=True when a new cluster was created."""
        log = logger.bind(title=article.title[:80])

        if article.embedding is not None:
            hit = self._repo.find_nearest_by_embedding(
                embedding=article.embedding,
                title=article.title,
                lookback_hours=self._lookback_hours,
            )
            if hit:
                cluster, cosine, trigram = hit
                method = self._semantic_verdict(cosine, trigram)
                if method:
                    self._repo.increment_count(cluster.id)
                    m.clusters_matched_total.add(1, {"method": method})
                    log.info("cluster_joined", method=method, cluster_id=cluster.id,
                             cosine=round(cosine, 3), trigram=round(trigram, 3))
                    return cluster, False
                log.debug("nearest_below_threshold", cluster_id=cluster.id,
                          cosine=round(cosine, 3), trigram=round(trigram, 3))

        existing = self._repo.find_similar(
            title=article.title,
            threshold=self._trigram_threshold,
            lookback_hours=self._lookback_hours,
        )
        if existing:
            self._repo.increment_count(existing.id)
            m.clusters_matched_total.add(1, {"method": "trigram"})
            log.info("cluster_joined", method="trigram", cluster_id=existing.id)
            return existing, False

        created = self._repo.create(ArticleCluster())  # category=None until the LLM fills it in
        return created, True

    def _semantic_verdict(self, cosine: float, trigram: float) -> str | None:
        if cosine >= self._cosine_threshold:
            return "embedding"
        if cosine >= self._hybrid_cosine and trigram >= self._hybrid_trigram:
            return "hybrid"
        return None
