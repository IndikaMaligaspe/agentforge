from langfuse import Langfuse
from langfuse import observe, get_client, propagate_attributes
from langfuse.langchain import CallbackHandler
from opentelemetry import trace
import os
import time
from dotenv import load_dotenv
from observability.logging import get_logger, RequestContext, log_with_props, log_execution_time

# Initialize logger
logger = get_logger(__name__)

load_dotenv()

# Initialize the Langfuse
logger.debug("Initializing Langfuse client")
langfuse = Langfuse(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    host=os.getenv("LANGFUSE_HOST"),
)


@observe(name="full_stack_agent Query")
def trace_agent_run(query: str):
    """
    Wrapper for agent execution with tracing.
    Integrates with Langfuse tracing and structured logging.
    """
    # Get the current request ID from logging context
    request_id = RequestContext.get_request_id()
    user_id = RequestContext.get_user_id() or "unknown"
    session_id = RequestContext.get_session_id() or "unknown"
    
    log_with_props(logger, "info", "Starting traced agent execution",
                  query_length=len(query),
                  request_id=request_id)
    
    # Import here to avoid circular imports
    from graph.workflow import get_workflow
    
    start_time = time.time()
    try:
        # Get the pre-compiled workflow graph
        graph = get_workflow()
        
        # Build tags with request context for correlation
        trace_tags = {
            "request_id": request_id,  # Link logs and traces with request_id
        }
        
        if user_id:
            trace_tags["user_id"] = user_id
        if session_id:
            trace_tags["session_id"] = session_id
            
        # 1. Define attributes that propagate to the LangGraph callback
        with propagate_attributes(
            user_id=user_id,
            tags=trace_tags
        ):
            # 2. Add additional metadata via OpenTelemetry attributes
            current_span = trace.get_current_span()
            current_span.set_attribute("request_id", request_id)
            
            # Add any additional context from RequestContext
            for key, value in RequestContext.get_all_context().items():
                if key not in ["request_id", "user_id", "session_id"]:
                    current_span.set_attribute(key, str(value))
            
            # 3. Create initial state for the graph
            initial_state = {
                "query": query,
                # Intent will be determined by query_router_node
            }
            
            # Create CallbackHandler at invoke time, not compile time
            langfuse_handler = CallbackHandler()
            
            # 4. Invoke the graph with the initial state
            result = graph.invoke(
                initial_state,
                config={"callbacks": [langfuse_handler]},  # per-request, not baked in
            )
            
            # Log execution time
            execution_time = time.time() - start_time
            log_with_props(logger, "info", "Traced agent execution completed",
                          execution_time_ms=round(execution_time * 1000, 2),
                          request_id=request_id)
            
            # Return the result
            return result
            
    except Exception as e:
        # Calculate execution time even for errors
        execution_time = time.time() - start_time
        
        # Log the error
        log_with_props(logger, "error", "Error in traced agent execution",
                      error=str(e),
                      execution_time_ms=round(execution_time * 1000, 2),
                      request_id=request_id,
                      exc_info=True)
        
        # Re-raise the exception
        raise
