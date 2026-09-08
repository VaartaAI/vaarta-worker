from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class SourceState:
    """
    Per-source fetch cursor. RSS sources use last_etag / last_modified for
    HTTP conditional GET; time-cursor sources (e.g. a search API) use
    last_fetched_at. Persisted in the source_state table.
    """
    source_key: str
    last_fetched_at: Optional[datetime] = None
    last_etag: Optional[str] = None
    last_modified: Optional[str] = None
