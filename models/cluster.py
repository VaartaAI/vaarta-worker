from dataclasses import dataclass
from typing import Optional
from datetime import datetime


@dataclass
class ArticleCluster:
    # Category is set by the LLM after summarization. Brand-new clusters
    # have category=None until their first summary lands.
    category: Optional[str] = None
    article_count: int = 1
    importance_score: float = 0.0
    id: Optional[int] = None
    created_at: Optional[datetime] = None
