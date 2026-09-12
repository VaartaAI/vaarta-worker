"""psycopg2 has no native pgvector adapter; pass vectors as text literals."""
from __future__ import annotations


def to_pgvector(vec: list[float] | None) -> str | None:
    """[0.1, 0.2] -> '[0.1,0.2]' for use with `%s::vector`. None stays None."""
    if vec is None:
        return None
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"
