import uuid
from abc import ABC, abstractmethod
from deepeval import assert_test
from deepeval.metrics import (
    AnswerRelevancyMetric,
    TaskCompletionMetric,
    ToolCorrectnessMetric,
)
from deepeval.test_case import LLMTestCase, ToolCall
from deepeval.dataset import Golden
from .utils import (
    get_evaluation_model,
    run_agent_and_get_response,
    setup_agent,
    MockedUser,
    build_golden_tool_mocks,
)
from backend.config.settings import settings


class BaseBenchmarksTestGenerator(ABC):
    """Abstract base class for benchmark test generators."""

    @abstractmethod
    def benchmark_test(self, golden: Golden):
        """
        Run a benchmark test for a single golden case.

        Args:
            golden (Golden): The golden test case data.
        """
        ...


class AgentBenchmarksTestGenerator(BaseBenchmarksTestGenerator):
    """Test generator for Agent benchmarks."""

    METRICS_MAP = {
        "relevancy": AnswerRelevancyMetric,
        "tool_correctness": ToolCorrectnessMetric,
        "completion": TaskCompletionMetric,
    }

    def __init__(self):
        self.eval_model = get_evaluation_model()

    def get_evaluation_metrics(self, golden: Golden) -> list:
        """
        Get the list of evaluation metrics for a specific golden case.

        Args:
            golden (Golden): The golden test case containing metric configuration.

        Returns:
            list: A list of DeepEval metrics.
        """
        evaluation_metrics = []
        verification_metrics = (
            golden.additional_metadata.get("verification_metrics", {}).items()
            if golden.additional_metadata
            else []
        )
        for metric, metric_meta in verification_metrics:
            evaluation_metrics.append(
                self.METRICS_MAP[metric](
                    threshold=metric_meta.get("score"),
                    model=self.eval_model,
                    include_reason=True,
                )
            )
        return evaluation_metrics

    async def benchmark_test(self, golden: Golden):
        """
        Execute the benchmark test for a single case using the Agent.

        Args:
            golden (Golden): The golden test case to run.
        """
        test_id = str(uuid.uuid4())

        input_query = golden.input
        expected_output = golden.expected_output
        expected_tools = golden.expected_tools or []

        golden_tool_mocks = build_golden_tool_mocks(expected_tools)

        metadata = golden.additional_metadata or {}

        agent = await setup_agent(
            mocked_user=MockedUser(
                id=getattr(settings, "BENCHMARKS_MOCKED_USER_ID", 1),
                token=getattr(settings, "BENCHMARKS_MOCKED_USER_TOKEN", "test-token"),
            ),
            use_mcp_mocks=metadata.get("use_mcp_mocks", False),
            golden_tool_mocks=golden_tool_mocks,
        )

        actual_output, tools_called_names = await run_agent_and_get_response(
            agent,
            input_query,
            test_id,
            approve_write_tools=metadata.get("approve_write_tools", False),
        )
        tools_called = [ToolCall(name=tool_name) for tool_name in tools_called_names]

        expected_tools_objects = (
            [ToolCall(name=tool.name) for tool in expected_tools] if expected_tools else []
        )

        test_case = LLMTestCase(
            input=input_query,
            actual_output=actual_output,
            expected_output=expected_output,
            tools_called=tools_called,
            expected_tools=expected_tools_objects,
        )
        evaluation_metrics = self.get_evaluation_metrics(golden)
        assert_test(test_case, evaluation_metrics)