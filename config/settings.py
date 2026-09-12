import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    database_url: str
    groq_api_key: str

    # Source defaults

    # Clustering
    # Bumped from 0.35 → 0.42 because clustering is now category-blind, so
    # the title-similarity match alone has to do the disambiguation work.
    cluster_similarity_threshold: float = 0.42
    cluster_lookback_hours: int = 48

    # Clustering — semantic (Gemini embeddings + pgvector). Auto-disabled when
    # GEMINI_API_KEY is empty; trigram matching is always the fallback.
    #   join if cosine >= cluster_embedding_threshold
    #   or  if cosine >= cluster_hybrid_embedding_threshold AND
    #          trigram >= cluster_hybrid_trigram_threshold
    clustering_use_embeddings: bool = True
    embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = 384            # must match articles.embedding vector(N)
    embedding_body_chars: int = 200            # body excerpt appended to the title
    embedding_requests_per_minute: int = 100   # free tier: 100 texts/min, each text = 1 request
    embedding_max_wait_seconds: float = 240.0  # give up (fall back to trigram) beyond this per feed
    cluster_embedding_threshold: float = 0.85
    cluster_hybrid_embedding_threshold: float = 0.80
    cluster_hybrid_trigram_threshold: float = 0.35   # 0.25 merged unrelated stories in calibration (2026-09-12)

    # Summarization
    max_articles_per_summary: int = 3
    summarization_delay_seconds: float = 2.0   # stay under per-minute RPM caps

    # Groq (primary provider)
    groq_model: str = "llama-3.3-70b-versatile"
    groq_daily_token_budget: int = 90_000      # reserve 10k buffer from 100k/day

    # Gemini (fallback provider — leave api_key blank to disable)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_daily_token_budget: int = 900_000   # buffer below typical 1M/day free tier

    # LLM worker (long-running)
    llm_worker_idle_seconds: int = 30          # sleep when queue is empty / budget exhausted
    queue_stuck_minutes: int = 30              # in_progress rows older than this get released
    queue_max_attempts: int = 5                # after N transient failures, give up on a cluster

    # Shared state (optional). When set, TokenBudget is Redis-backed so multiple
    # LLM workers share one daily counter per provider. Empty = per-worker
    # in-memory counters (only safe for a single worker).
    redis_url: str = ""

    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.environ["DATABASE_URL"],
            groq_api_key=os.environ.get("GROQ_API_KEY", ""),
            cluster_similarity_threshold=float(os.getenv("CLUSTER_THRESHOLD", "0.42")),
            cluster_lookback_hours=int(os.getenv("CLUSTER_LOOKBACK_HOURS", "48")),
            clustering_use_embeddings=os.getenv("CLUSTERING_USE_EMBEDDINGS", "true").lower() in ("1", "true", "yes"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "gemini-embedding-001"),
            embedding_dimensions=int(os.getenv("EMBEDDING_DIMENSIONS", "384")),
            embedding_body_chars=int(os.getenv("EMBEDDING_BODY_CHARS", "200")),
            embedding_requests_per_minute=int(os.getenv("EMBEDDING_REQUESTS_PER_MINUTE", "100")),
            embedding_max_wait_seconds=float(os.getenv("EMBEDDING_MAX_WAIT_SECONDS", "240")),
            cluster_embedding_threshold=float(os.getenv("CLUSTER_EMBEDDING_THRESHOLD", "0.85")),
            cluster_hybrid_embedding_threshold=float(os.getenv("CLUSTER_HYBRID_EMBEDDING_THRESHOLD", "0.80")),
            cluster_hybrid_trigram_threshold=float(os.getenv("CLUSTER_HYBRID_TRIGRAM_THRESHOLD", "0.35")),
            max_articles_per_summary=int(os.getenv("MAX_ARTICLES_PER_SUMMARY", "3")),
            summarization_delay_seconds=float(os.getenv("SUMMARIZATION_DELAY", "2.0")),
            groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            groq_daily_token_budget=int(os.getenv("GROQ_DAILY_TOKEN_BUDGET", "90000")),
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            gemini_daily_token_budget=int(os.getenv("GEMINI_DAILY_TOKEN_BUDGET", "900000")),
            llm_worker_idle_seconds=int(os.getenv("LLM_WORKER_IDLE_SECONDS", "30")),
            queue_stuck_minutes=int(os.getenv("QUEUE_STUCK_MINUTES", "30")),
            queue_max_attempts=int(os.getenv("QUEUE_MAX_ATTEMPTS", "5")),
            redis_url=os.getenv("REDIS_URL", ""),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )
