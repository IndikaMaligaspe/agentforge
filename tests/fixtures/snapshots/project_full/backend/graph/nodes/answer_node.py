"""
Answer Node for the LangGraph workflow.

This module contains the answer_node function that shapes the final answer
based on the results produced by the agent dispatched by supervisor_node.
Replace the formatting logic with a project-specific renderer (widgets,
tables, charts, etc.) as needed.
"""
import time
from typing import Any, Dict

from ..state import AgentState
from observability.logging import get_logger, log_with_props, RequestContext

logger = get_logger(__name__)


def _shape_answer(result_obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Turn an agent's raw result dict into a user-facing answer payload.
    Default shape is text-only; projects should customize this function to
    produce whatever structure their frontend consumes.
    """
    if not result_obj.get("success", False):
        return {
            "type": "text",
            "data": f"The query failed: {result_obj.get('error') or 'unknown error'}",
        }
    return {
        "type": "text",
        "data": result_obj.get("output", ""),
    }


def answer_node(state: AgentState) -> AgentState:
    """
    Read the latest result from ``state['agent_result']`` and write the shaped
    payload into ``state['final_answer']``.
    """
    node_name = "answer_node"
    request_id = RequestContext.get_request_id()
    intent = state.get("intent", "data")

    log_with_props(
        logger, "info", f"Entering {node_name}",
        node=node_name, request_id=request_id, intent=intent,
    )

    try:
        results = state.get("agent_result") or []
        result_obj: Dict[str, Any] = results[-1] if results else {}

        if not result_obj:
            log_with_props(
                logger, "error",
                f"{node_name}: no agent_result present",
                node=node_name, request_id=request_id,
            )

        return {**state, "final_answer": _shape_answer(result_obj)}

    except Exception as exc:
        log_with_props(
            logger, "error", f"Error in {node_name}",
            node=node_name, request_id=request_id, error=str(exc), exc_info=True,
        )
        error_info = {
            "error": str(exc),
            "node": node_name,
            "timestamp": time.time(),
        }
        return {
            **state,
            "errors": state.get("errors", []) + [error_info],
            "final_answer": {"type": "text", "data": f"An error occurred: {exc}"},
        }