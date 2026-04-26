"""
LangGraph pipeline state.

PipelineState is a TypedDict where fields annotated with a reducer function
are merged automatically when multiple nodes update the same key.
"""
from __future__ import annotations
import uuid
from typing import TypedDict, Annotated
from operator import add


def _sum_ints(a: int, b: int) -> int:
    return a + b


class PipelineState(TypedDict):
    # ── Execution metadata ───────────────────────────────────────────────
    run_id: str
    categories: list[str]            # categories to fetch; empty = fetcher defaults

    # ── Ingestion phase ──────────────────────────────────────────────────
    new_cluster_ids: Annotated[list[int], add]   # extends on merge
    articles_fetched: Annotated[int, _sum_ints]
    ingestion_errors: Annotated[list[str], add]

    # ── Analysis phase ───────────────────────────────────────────────────
    summaries_created: Annotated[int, _sum_ints]
    analysis_errors: Annotated[list[str], add]

    # ── Trend phase ──────────────────────────────────────────────────────
    trend_updates: Annotated[int, _sum_ints]

    # ── Control ──────────────────────────────────────────────────────────
    phase: str   # "ingestion" | "analysis" | "trend" | "done"


def initial_state(categories: list[str] | None = None) -> PipelineState:
    """Return a clean initial state for a new pipeline run."""
    return PipelineState(
        run_id=str(uuid.uuid4()),
        categories=categories or [],
        new_cluster_ids=[],
        articles_fetched=0,
        ingestion_errors=[],
        summaries_created=0,
        analysis_errors=[],
        trend_updates=0,
        phase="ingestion",
    )
