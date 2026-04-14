import pytest
from backend.tests.benchmarks.generators import AgentBenchmarksTestGenerator
from backend.tests.benchmarks.runner import BenchmarksRunner
from backend.tests.benchmarks.datasets import agent_benchmarks_dataset


pytestmark = pytest.mark.benchmarks

runner = BenchmarksRunner(
    batch_size=1,
    dataset=agent_benchmarks_dataset(),
    tests_generator=AgentBenchmarksTestGenerator(),
)
test_functions = runner.init_tests()

for function in test_functions:
    globals()[function.__name__] = function