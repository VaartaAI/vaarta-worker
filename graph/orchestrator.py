"""
Pipeline graph builder.

Topology:
    ingestion ──(new clusters?)──► analysis ──► trend ──► END
                └──(no clusters)──────────────► trend

Call build_pipeline() to get a compiled, ready-to-invoke LangGraph runnable.
"""
from __future__ import annotations
from langgraph.graph import StateGraph, END

from agents.state import PipelineState
from agents.ingestion_agent import IngestionAgent
from agents.analysis_agent import AnalysisAgent
from agents.trend_agent import TrendAgent
from graph.routing import route_after_ingestion


def build_pipeline(
    ingestion_agent: IngestionAgent,
    analysis_agent: AnalysisAgent,
    trend_agent: TrendAgent,
):
    """
    Assemble and compile the stateful LangGraph pipeline.

    Returns a compiled graph that accepts a PipelineState dict and
    returns the final merged PipelineState.
    """
    graph = StateGraph(PipelineState)

    # Register nodes — each node is a callable(state) -> partial_state_dict
    graph.add_node("ingestion", ingestion_agent)
    graph.add_node("analysis", analysis_agent)
    graph.add_node("trend", trend_agent)

    # Entry point
    graph.set_entry_point("ingestion")

    # After ingestion: go to analysis OR jump straight to trend
    graph.add_conditional_edges(
        "ingestion",
        route_after_ingestion,
        {
            "analysis": "analysis",
            "trend": "trend",
        },
    )

    # Fixed edges
    graph.add_edge("analysis", "trend")
    graph.add_edge("trend", END)

    return graph.compile()
