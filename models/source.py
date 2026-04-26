from dataclasses import dataclass
from typing import Optional


@dataclass
class Source:
    name: str
    domain: str
    trust_score: int = 3
    political_lean: int = 0
    id: Optional[int] = None
