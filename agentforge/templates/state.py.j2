"""
State definitions for the agent workflow graph.

This module defines the TypedDict classes that represent the state
of the agent workflow graph. These are used to type-check the state
transitions in the workflow graph.
"""
from typing import Any, Dict, List, Optional, TypedDict, Union


class AgentState(TypedDict, total=False):
    """
    State passed between nodes in the agent workflow graph.
    
    This TypedDict defines the structure of the state object that is
    passed between nodes in the workflow graph. It includes fields for
    the user's query, the selected agent, the agent's response, and
    any additional context needed for processing.
    
    Attributes:
        query: The user's original query text
        intent: The detected intent/agent key to route to
        agent_response: The response from the selected agent
        validated: Whether the response has been validated
        feedback: User feedback on the response
        improved_response: Improved response after feedback
        attempt_count: Number of feedback loop iterations
        context: Additional context for the request
        error: Error information if something went wrong
    """
    # Core fields
    query: str
    intent: str
    agent_response: Optional[str]
    
    # Validation fields
    validated: bool
    validation_result: Optional[Dict[str, Any]]
    
    # Feedback loop fields
    feedback: Optional[str]
    improved_response: Optional[str]
    attempt_count: int
    
    # Context and metadata
    context: Dict[str, Any]
    request_id: str
    session_id: Optional[str]
    user_id: Optional[str]
    
    # Error handling
    error: Optional[Dict[str, Any]]