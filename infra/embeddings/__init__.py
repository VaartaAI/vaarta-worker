from infra.embeddings.base import EmbeddingClient, EmbeddingError, EmbeddingQuotaExhausted
from infra.embeddings.gemini_embeddings import GeminiEmbeddingClient
from infra.embeddings.text import embedding_text, clean_html

__all__ = [
    "EmbeddingClient",
    "EmbeddingError",
    "EmbeddingQuotaExhausted",
    "GeminiEmbeddingClient",
    "embedding_text",
    "clean_html",
    "build_embedder",
]


def build_embedder(settings) -> EmbeddingClient | None:
    """Return the configured embedding client, or None if embeddings are off."""
    if not settings.clustering_use_embeddings or not settings.gemini_api_key:
        return None
    return GeminiEmbeddingClient(
        api_key=settings.gemini_api_key,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        per_minute=settings.embedding_requests_per_minute,
        max_wait_seconds=settings.embedding_max_wait_seconds,
    )
