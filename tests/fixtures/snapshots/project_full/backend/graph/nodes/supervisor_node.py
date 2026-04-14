"""
Supervisor Node for the LangGraph workflow.

This module contains the supervisor_node function that dispatches queries
to the appropriate agent based on the intent set by the query_router_node.
"""

from ..state import AgentState
from agents.registry import AgentRegistry
from observability.logging import get_logger, log_with_props, log_execution_time, RequestContext

logger = get_logger(__name__)

def supervisor_node(state: AgentState) -> AgentState:
    """
    Supervisor / Orchestrator node.
    
    Reads state["intent"], looks up the registered agent, calls run(),
    and writes the result to state["agent_result"].
    
    Raises AssertionError if the agent returns an empty or malformed result
    (prevents silent blank-response propagation — Risk 1 mitigation).
    
    Args:
        state: The current workflow state
        
    Returns:
        Updated state with agent_result, agent_name, and needs_validation
    """
    node_name = "supervisor_node"
    request_id = RequestContext.get_request_id()
    intent = state.get("intent", "data")

    log_with_props(logger, "info", f"Entering {node_name}",
                   node=node_name, request_id=request_id, intent=intent)

    try:
        # Try to get a warmed-up instance first
        try:
            agent = AgentRegistry.get_instance(intent)
            log_with_props(logger, "debug", f"Using warmed-up agent instance for '{intent}'",
                          node=node_name, request_id=request_id)
        except RuntimeError:
            # Fall back to creating a new instance if warm_up hasn't been called
            agent_cls = AgentRegistry.get(intent)
            agent = agent_cls()
            log_with_props(logger, "warning", 
                          f"Creating new agent instance for '{intent}' - AgentRegistry not warmed up",
                          node=node_name, request_id=request_id)

        with log_execution_time(logger, f"{node_name}_{intent}_execution"):
            result = agent.run(state["query"])

        # --- Risk 1 Mitigation: hard assertion on non-empty output ---
        assert result, (
            f"supervisor_node: agent '{intent}' returned empty result. "
            "This would cause a blank response in answer_node."
        )
        assert "success" in result, f"agent '{intent}' result missing 'success' key"
        assert "output" in result,  f"agent '{intent}' result missing 'output' key"

        needs_validation = agent.needs_validation

        log_with_props(logger, "info", f"Agent '{intent}' completed",
                       node=node_name, request_id=request_id,
                       success=result.get("success"),
                       needs_validation=needs_validation)

        return {
            **state,
            "agent_result": [result],        # list for Annotated[List, operator.add]
            "agent_name": intent,
            "needs_validation": needs_validation,
        }

    except KeyError as e:
        log_with_props(logger, "error", f"Unknown intent '{intent}' in registry",
                       node=node_name, request_id=request_id, error=str(e))
        raise
    except AssertionError as e:
        log_with_props(logger, "error", "supervisor_node assertion failed",
                       node=node_name, request_id=request_id, error=str(e))
        raise
    except Exception as e:
        log_with_props(logger, "error", f"Error in {node_name}",
                       node=node_name, request_id=request_id,
                       error=str(e), exc_info=True)
        raise