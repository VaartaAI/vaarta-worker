import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    database_url: str
    newsapi_key: str
    groq_api_key: str
    newsapi_country: str = "in"
    newsapi_page_size: int = 20
    cluster_similarity_threshold: float = 0.35
    cluster_lookback_hours: int = 48
    max_articles_per_summary: int = 3
    groq_model: str = "llama-3.3-70b-versatile"
    summarization_delay_seconds: float = 2.0  # stay under 30 RPM free tier

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.environ["DATABASE_URL"],
            newsapi_key=os.environ["NEWSAPI_KEY"],
            groq_api_key=os.environ["GROQ_API_KEY"],
            newsapi_country=os.getenv("NEWSAPI_COUNTRY", "in"),
            newsapi_page_size=int(os.getenv("NEWSAPI_PAGE_SIZE", "20")),
            cluster_similarity_threshold=float(os.getenv("CLUSTER_THRESHOLD", "0.35")),
            cluster_lookback_hours=int(os.getenv("CLUSTER_LOOKBACK_HOURS", "48")),
            max_articles_per_summary=int(os.getenv("MAX_ARTICLES_PER_SUMMARY", "3")),
            groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            summarization_delay_seconds=float(os.getenv("SUMMARIZATION_DELAY", "2.0")),
        )
