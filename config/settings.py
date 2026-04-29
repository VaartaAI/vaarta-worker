import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    database_url: str
    newsapi_key: str
    groq_api_key: str

    # Source defaults
    newsapi_country: str = "in"
    newsapi_page_size: int = 20

    # Clustering
    # Bumped from 0.35 → 0.42 because clustering is now category-blind, so
    # the title-similarity match alone has to do the disambiguation work.
    cluster_similarity_threshold: float = 0.42
    cluster_lookback_hours: int = 48

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

    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.environ["DATABASE_URL"],
            newsapi_key=os.environ.get("NEWSAPI_KEY", ""),
            groq_api_key=os.environ.get("GROQ_API_KEY", ""),
            newsapi_country=os.getenv("NEWSAPI_COUNTRY", "in"),
            newsapi_page_size=int(os.getenv("NEWSAPI_PAGE_SIZE", "20")),
            cluster_similarity_threshold=float(os.getenv("CLUSTER_THRESHOLD", "0.42")),
            cluster_lookback_hours=int(os.getenv("CLUSTER_LOOKBACK_HOURS", "48")),
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
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )
