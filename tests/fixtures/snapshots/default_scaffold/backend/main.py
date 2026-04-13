from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import time
from typing import Union, Dict, Any, Optional
from contextlib import asynccontextmanager
from observability.tracing import trace_agent_run, langfuse
from observability.logging import get_logger, RequestContext, log_with_props, log_execution_time
from middleware.logging_middleware import LoggingMiddleware
from security.auth import get_api_key as auth_dep
from security.sanitizer import sanitize_for_log

# Setup Logging with our centralized configuration
logger = get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for the FastAPI application.

    This function is called when the application starts up and shuts down.
    It performs the following tasks on startup:
1. Validates Langfuse authentication
2. Warms up the AgentRegistry
    """
    logger.info("Starting full_featured_project API")

    # Validate Langfuse auth at startup
    try:
        langfuse.auth_check()
        logger.info("Langfuse auth check passed")
    except Exception as e:
        logger.warning(f"Langfuse auth check failed: {e} — traces may not appear")

    # Warm up all registered agents (decorators run on import of the agents package)
    try:
        import agents  # triggers @AgentRegistry.register decorators
        from agents.registry import AgentRegistry
        logger.info(f"AgentRegistry ready: {AgentRegistry.get_all_keys()}")
    except Exception as e:
        logger.error(f"Failed to load AgentRegistry: {e}", exc_info=True)

    yield  # This is where the application runs

    # Shutdown logic (if any) would go here
    logger.info("Shutting down full_featured_project API")

app = FastAPI(title="Full Featured API", lifespan=lifespan)

# Add middleware (order matters - logging middleware should be first to catch all requests)
app.add_middleware(LoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000/", "https://app.example.com/"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Bounded query length prevents ReDoS and unbounded LLM cost
class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=5000, description="Natural language query")

class QueryResponse(BaseModel):
    success: bool = Field(..., description="Indicates if the query was processed successfully.")
    answer: Union[str, Dict[str, Any]] = Field(None, description="The answer to the query, which can be a string or a widget object.")
    error: Optional[str] = None
    trace_id: Optional[str] = None

@app.get("/")
def read_root():
    logger.debug("Root endpoint accessed")
    return {"message": "Welcome to the Full Featured API"}

@app.get("/health")
def health_check():
    logger.debug("Health check endpoint accessed")
    return {"status": "healthy"}

@app.post("/query", response_model=QueryResponse)
def handle_query(request: QueryRequest, _key: str = Depends(auth_dep)):
    """ Main endpoint to handle natural language queries """
    query = request.query
    request_id = RequestContext.get_request_id()

    # Log the incoming request
    log_with_props(logger, "info", "Received query request",
                  query_length=len(query),
                  query_preview=query[:100] + "..." if len(query) > 100 else query,
                  request_id=request_id)

    # Query length is enforced by QueryRequest.Field(min_length, max_length);
    # add domain-specific content validation here if your project needs it.

    try:
        # Measure execution time
        start_time = time.time()

        # Process the query through the workflow
        with log_execution_time(logger, "query_processing"):
            result = trace_agent_run(query)

        # Extract the final answer from the result
        final_answer = result.get('final_answer')

        # Log success
        execution_time = time.time() - start_time
        log_with_props(logger, "info", "Query processed successfully",
                      execution_time_ms=round(execution_time * 1000, 2),
                      has_answer=bool(final_answer),
                      request_id=request_id)

        # Return the response
        return {
            "success": True,
            "answer": final_answer,
            "error": None,
            "trace_id": request_id
        }

    except Exception as e:
        # Log full error internally; return only a generic message to the client
        log_with_props(logger, "error", "Error processing query",
                      error=str(e),
                      request_id=request_id,
                      exc_info=True)

        return {
            "success": False,
            "answer": None,
            "error": "An internal error occurred while processing your query. Please try again.",
            "trace_id": request_id
        }
@app.post("/analyze", response_model=QueryResponse)
def handle_query(request: QueryRequest, _key: str = Depends(auth_dep)):
    """ Main endpoint to handle natural language queries """
    query = request.query
    request_id = RequestContext.get_request_id()

    # Log the incoming request
    log_with_props(logger, "info", "Received query request",
                  query_length=len(query),
                  query_preview=query[:100] + "..." if len(query) > 100 else query,
                  request_id=request_id)

    # Query length is enforced by QueryRequest.Field(min_length, max_length);
    # add domain-specific content validation here if your project needs it.

    try:
        # Measure execution time
        start_time = time.time()

        # Process the query through the workflow
        with log_execution_time(logger, "query_processing"):
            result = trace_agent_run(query)

        # Extract the final answer from the result
        final_answer = result.get('final_answer')

        # Log success
        execution_time = time.time() - start_time
        log_with_props(logger, "info", "Query processed successfully",
                      execution_time_ms=round(execution_time * 1000, 2),
                      has_answer=bool(final_answer),
                      request_id=request_id)

        # Return the response
        return {
            "success": True,
            "answer": final_answer,
            "error": None,
            "trace_id": request_id
        }

    except Exception as e:
        # Log full error internally; return only a generic message to the client
        log_with_props(logger, "error", "Error processing query",
                      error=str(e),
                      request_id=request_id,
                      exc_info=True)

        return {
            "success": False,
            "answer": None,
            "error": "An internal error occurred while processing your query. Please try again.",
            "trace_id": request_id
        }
@app.post("/visualize", response_model=QueryResponse)
def handle_query(request: QueryRequest, _key: str = Depends(auth_dep)):
    """ Main endpoint to handle natural language queries """
    query = request.query
    request_id = RequestContext.get_request_id()

    # Log the incoming request
    log_with_props(logger, "info", "Received query request",
                  query_length=len(query),
                  query_preview=query[:100] + "..." if len(query) > 100 else query,
                  request_id=request_id)

    # Query length is enforced by QueryRequest.Field(min_length, max_length);
    # add domain-specific content validation here if your project needs it.

    try:
        # Measure execution time
        start_time = time.time()

        # Process the query through the workflow
        with log_execution_time(logger, "query_processing"):
            result = trace_agent_run(query)

        # Extract the final answer from the result
        final_answer = result.get('final_answer')

        # Log success
        execution_time = time.time() - start_time
        log_with_props(logger, "info", "Query processed successfully",
                      execution_time_ms=round(execution_time * 1000, 2),
                      has_answer=bool(final_answer),
                      request_id=request_id)

        # Return the response
        return {
            "success": True,
            "answer": final_answer,
            "error": None,
            "trace_id": request_id
        }

    except Exception as e:
        # Log full error internally; return only a generic message to the client
        log_with_props(logger, "error", "Error processing query",
                      error=str(e),
                      request_id=request_id,
                      exc_info=True)

        return {
            "success": False,
            "answer": None,
            "error": "An internal error occurred while processing your query. Please try again.",
            "trace_id": request_id
        }
