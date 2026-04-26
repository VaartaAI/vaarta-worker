from dataclasses import dataclass
from typing import Optional
from datetime import datetime


@dataclass
class ArticleCluster:
    category: str
    article_count: int = 1
    importance_score: float = 0.0
    id: Optional[int] = None
    created_at: Optional[datetime] = None
