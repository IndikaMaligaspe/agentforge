"""
Feedback node for the agent workflow graph.

This node handles user feedback on agent responses and routes the feedback
to the appropriate agent for improvement.
"""
from typing import Any, Dict, Literal

from ...agents.registry import AgentRegistry
from ..state import AgentState


MAX_FEEDBACK_ATTEMPTS = 5


def feedback_node(state: AgentState) -> AgentState:
    """
    Evaluate the quality of the current answer and decide whether to keep it,
    retry via improve_answer_node, or surface an error.

    This default implementation is intentionally conservative: any answer with
    a non-empty ``final_answer`` is accepted. Replace the heuristic below with
    a project-specific evaluator (e.g., LLM-graded correctness, rule checks).
    """
    final_answer = state.get("final_answer")
    attempt_count = state.get("attempt_count", 0)

    if final_answer:
        state["feedback_decision"] = "accept"
    elif attempt_count < MAX_FEEDBACK_ATTEMPTS:
        state["feedback_decision"] = "improve"
    else:
        state["feedback_decision"] = "fail"

    return state


def improve_answer_node(state: AgentState) -> AgentState:
    """
    Re-invoke the original agent with the prior attempt's context so it can
    produce a better answer.  Attempt counter is incremented here.
    """
    intent = state.get("intent", "sql")
    query = state.get("query", "")
    prior = state.get("final_answer", "")

    state["attempt_count"] = state.get("attempt_count", 0) + 1

    agent = AgentRegistry.create(intent)
    retry_prompt = (
        f"The previous answer was insufficient. Produce an improved answer.\n\n"
        f"Original query: {query}\n"
        f"Previous answer: {prior}\n"
    )
    result: Dict[str, Any] = agent.run(retry_prompt)
    state["final_answer"] = result.get("output", "")
    return state


def error_end_node(state: AgentState) -> AgentState:
    """
    Terminal node reached when the feedback loop exhausts its retry budget.
    Records the failure mode on the state; the caller decides how to surface it.
    """
    state["error"] = (
        state.get("error")
        or f"Answer quality insufficient after {MAX_FEEDBACK_ATTEMPTS} attempts"
    )
    return state


def feedback_router(state: AgentState) -> Literal["accept", "improve", "fail"]:
    """Conditional edge dispatcher consumed by workflow.py's StateGraph."""
    decision = state.get("feedback_decision", "accept")
    if decision not in ("accept", "improve", "fail"):
        return "accept"
    return decision  # type: ignore[return-value]