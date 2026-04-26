from __future__ import annotations
from models.article import Article
from models.cluster import ArticleCluster
from db.repositories.cluster_repository import ClusterRepository
from config.settings import Settings


class ClusteringService:

    def __init__(self, cluster_repo: ClusterRepository, settings: Settings):
        self._repo = cluster_repo
        self._threshold = settings.cluster_similarity_threshold
        self._lookback_hours = settings.cluster_lookback_hours

    def find_or_create_cluster(
        self,
        article: Article,
        category: str
    ) -> tuple[ArticleCluster, bool]:
        """
        Returns (cluster, is_new).
        is_new = True if a new cluster was created.
        """
        existing = self._repo.find_similar(
            title=article.title,
            category=category,
            threshold=self._threshold,
            lookback_hours=self._lookback_hours
        )

        if existing:
            self._repo.increment_count(existing.id)
            return existing, False

        new_cluster = ArticleCluster(category=category)
        created = self._repo.create(new_cluster)
        return created, True
