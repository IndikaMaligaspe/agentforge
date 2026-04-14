import subprocess
from backend.tests.benchmarks.test_graph_agent import test_functions


def trigger_benchmarks_command():
    """Run the full benchmark suite via deepeval."""
    print("Starting benchmarks...")

    result = subprocess.run(
        [
            "uv",
            "run",
            "deepeval",
            "test",
            "run",
            "backend/tests/benchmarks/test_graph_agent.py",
            "--num-processes",
            "2",
        ],
        capture_output=True,
        text=True,
    )
    print(f"Benchmarks finished with return code: {result.returncode}")


def trigger_benchmarks_command_parallel():
    """Run each benchmark batch in parallel."""
    parallel_commands = []
    for item in test_functions:
        parallel_commands.append(
            f"uv run deepeval test run backend/tests/benchmarks/test_graph_agent.py -k {item.__name__}"
        )
    run_command = " & ".join(parallel_commands)
    subprocess.run(
        [
            "bash",
            "-c",
            f"""
        {run_command}
        done
        wait
        """,
        ]
    )