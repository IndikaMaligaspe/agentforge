from pathlib import Path
from unittest.mock import AsyncMock, patch
import uuid
import json
from dataclasses import dataclass

from pydantic import BaseModel, field_validator
from deepeval.test_case.llm_test_case import ToolCall
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver

from backend.agents.graph_agent import GraphAgent
from backend.config.settings import settings


class ToolMockResponse(BaseModel):
    """Standardized mock response for an MCP tool.

    Normalizes data from both golden tool outputs (strings) and
    base_mcp_mocks.json (dicts) into a consistent string format.
    """

    response: str

    @field_validator("response", mode="before")
    @classmethod
    def serialize_response(cls, v):
        """Convert non-string responses (dicts, lists) to JSON strings."""
        if not isinstance(v, str):
            return json.dumps(v)
        return v


@dataclass
class MockedUser:
    id: int
    token: str


def get_evaluation_model():
    """
    Returns a DeepEval-compatible model for evaluation metrics.

    Uses self-hosted model if configured, otherwise falls back to OpenAI's default.
    """
    from deepeval.models import LiteLLMModel

    self_hosted_url = getattr(settings, "BENCHMARKS_EVALUATION_MODEL_URL", None)

    if self_hosted_url:
        return LiteLLMModel(
            model=getattr(settings, "BENCHMARKS_EVALUATION_MODEL", "gpt-4"),
            api_base=self_hosted_url,
            api_key=getattr(settings, "BENCHMARKS_EVALUATION_MODEL_API_KEY", ""),
            temperature=0,
            include_reasoning=False,
        )
    return None


def load_base_mock_data():
    """Load base mock MCP data from base_mcp_mocks.json.

    Returns:
        dict: Base mock data dictionary with tool responses
    """
    mock_data_path = Path(__file__).parent.parent / "base_mcp_mocks.json"
    if not mock_data_path.exists():
        return {}

    with open(mock_data_path, "r") as f:
        return json.load(f)


def build_golden_tool_mocks(expected_tools: list[ToolCall] | None) -> dict[str, str]:
    """Build a tool-name-to-output mapping from a Golden's expected_tools.

    Only includes tools whose output field is not None. Tools with output=None
    are excluded so they fall through to base mock data or real calls.

    Args:
        expected_tools: List of ToolCall objects from a Golden, or None.

    Returns:
        dict: Mapping of tool_name -> output_value for tools with explicit outputs.
    """
    if not expected_tools:
        return {}

    golden_mocks = {}
    for tool_call in expected_tools:
        if tool_call.output is not None:
            golden_mocks[tool_call.name] = tool_call.output
    return golden_mocks


def _collect_stream_events(event, actual_output: str, tools_called: list[str]):
    """Extract actual_output text and tool names from a single stream event.

    Returns the (possibly extended) actual_output string.
    tools_called is mutated in-place.
    """
    if event.get("event") == "on_chat_model_stream":
        meta = event.get("metadata", {})
        if meta.get("langgraph_node") == "agent":
            chunk = event.get("data", {}).get("chunk")
            if chunk:
                content = getattr(chunk, "content", "")
                if isinstance(content, str) and content:
                    actual_output += content

    if event.get("event") == "on_chain_end":
        meta = event.get("metadata", {})
        if meta.get("langgraph_node") == "tools":
            data = event.get("data", {})
            output = data.get("output")
            messages = None
            if isinstance(output, dict):
                messages = output.get("messages", [])
            elif hasattr(output, "messages"):
                messages = output.messages
            if messages:
                for msg in messages:
                    if isinstance(msg, ToolMessage) and getattr(msg, "name", None):
                        tools_called.append(msg.name)

    return actual_output


async def run_agent_and_get_response(
    agent: GraphAgent,
    input_query: str,
    test_id: str,
    approve_write_tools: bool = False,
):
    """
    Helper function to run GraphAgent and extract response with tool calls.

    Args:
        agent: The GraphAgent instance from fixture
        input_query: The user query to send to the agent
        test_id: Unique test identifier to prevent thread_id collisions
        approve_write_tools: If True, auto-approve write tool calls

    Returns:
        tuple: (actual_output, tools_called) where actual_output is the agent's
               response and tools_called is a list of tool names that were invoked
    """
    config = {
        "configurable": {
            "thread_id": f"test-{test_id}",
            "user": agent.user,
        }
    }

    actual_output = ""
    tools_called = []

    graph = await agent.get_graph()

    async for event in graph.astream_events(
        {"messages": [HumanMessage(content=input_query)]},
        config=config,
        version="v2",
    ):
        actual_output = _collect_stream_events(event, actual_output, tools_called)

    return actual_output, tools_called


async def setup_agent(
    mocked_user: MockedUser,
    use_mcp_mocks: bool,
    golden_tool_mocks: dict[str, str] | None = None,
):
    """Set up the agent for testing with optional MCP mocking.

    Args:
        mocked_user: Mock user data
        use_mcp_mocks: Whether to use mocked MCP responses
        golden_tool_mocks: Optional per-test tool mock overrides from Golden's
                           expected_tools. Keys are tool names, values are outputs.

    Returns:
        GraphAgent instance ready for testing
    """

    class MockConversation:
        id = 123
        thread_id = f"test-thread-{uuid.uuid4()}"

    mock_conversation = MockConversation()

    saver = MemorySaver()

    agent_instance = GraphAgent(
        user=mocked_user,
        conversation=mock_conversation,
        saver=saver,
    )

    return agent_instance