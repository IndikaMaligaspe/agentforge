"""
workflow.py — Supervisor-based workflow with compile-once pattern.

This module defines a LangGraph StateGraph that orchestrates the agent workflow.
"""

from langgraph.graph import StateGraph, END
from typing import Dict, Any
from .state import AgentState
from .nodes.query_router_node import query_router_node
from .nodes.supervisor_node import supervisor_node
from .nodes.answer_node import answer_node
from .nodes.validation_node import validation_node
from .nodes.feedback_node import (
    feedback_node,
    improve_answer_node,
    error_end_node,
    feedback_router,
    MAX_FEEDBACK_ATTEMPTS,
)
from observability.logging import get_logger
import agents  # ensure all @AgentRegistry.register decorators execute

logger = get_logger(__name__)

def _build_graph() -> StateGraph:
    """
    Build the workflow graph with supervisor_node.

    This function creates a LangGraph workflow with the following components:
    - query_router: Classifies queries as 'sql', 'analytics'    - supervisor: Dispatches to the appropriate agent based on intent
- validator: Validates agent results (conditional)    - answer: Formats the final answer
- feedback: Evaluates answer quality
    - improve_answer: Improves low-quality answers
    - error_end: Handles persistent low-quality answers
    Returns:
        Compiled LangGraph workflow
    """
    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("query_router", query_router_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("validator", validation_node)
    graph.add_node("answer", answer_node)
    graph.add_node("feedback", feedback_node)
    graph.add_node("improve_answer", improve_answer_node)
    graph.add_node("error_end", error_end_node)

    # Set entry point
    graph.set_entry_point("query_router")

    # query_router → supervisor (all intents go here; supervisor dispatches internally)
    graph.add_edge("query_router", "supervisor")

    # supervisor → validator OR answer based on needs_validation flag
    graph.add_conditional_edges(
        "supervisor",
        lambda state: "validator" if state.get("needs_validation") else "answer",
        {"validator": "validator", "answer": "answer"},
    )

    # Validator → answer
    graph.add_edge("validator", "answer")

    # Answer → feedback
    graph.add_edge("answer", "feedback")

    # Feedback conditional edges
    graph.add_conditional_edges(
        "feedback",
        feedback_router,
        {"accept": END, "improve": "improve_answer", "fail": "error_end"},
    )

    graph.add_edge("improve_answer", "feedback")
    graph.add_edge("error_end", END)

    return graph


# ── Compile once at module load ──────────────────────────────────────────────
# Risk 2 Mitigation: do NOT attach CallbackHandler() here.
# Pass it at invoke time via config={"callbacks": [CallbackHandler()]}.
_COMPILED_GRAPH = _build_graph().compile()
logger.info("workflow: graph compiled and cached at startup")


def get_workflow():
    """Return the module-level singleton compiled graph."""
    return _COMPILED_GRAPH