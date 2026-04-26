"""
Conditional edge functions for the LangGraph pipeline graph.

Each function receives the current PipelineState and returns a string
that LangGraph uses to look up the next node in the edges map.
"""
from __future__ import annotations
from agents.state import PipelineState


def route_after_ingestion(state: PipelineState) -> str:
    """
    If ingestion produced no new clusters (all articles were duplicates, or
    every category failed), skip the analysis node and go straight to trend
    scoring — there is nothing new to summarize.
    """
    if not state.get("new_cluster_ids"):
        return "trend"
    return "analysis"
