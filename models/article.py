from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from models.source import Source


@dataclass
class Article:
    url: str
    title: str
    source: "Source"
    body_text: str = ""
    published_at: Optional[datetime] = None
    cluster_id: Optional[int] = None
    image_url: Optional[str] = None
    id: Optional[int] = None
