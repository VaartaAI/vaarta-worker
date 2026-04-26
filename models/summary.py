from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class Summary:
    cluster_id: int
    summary_text: str
    why_it_matters: str
    category: str
    entities: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)
    is_safe: bool = True
    sources_agree: bool = True
    deep_explainer: Optional[str] = None
    id: Optional[int] = None
