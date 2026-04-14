"""
End-to-end scaffold test for examples/project.full.yaml.

Renders the maximalist config to a tmpdir and verifies:
- Every expected output file is present.
- Every generated .py file parses as valid Python (ast.parse).
- No forbidden strings ("madgicx", "slack", "webhook") appear in any file.
- requirements.txt contains all expected packages.
- backend/main.py imports verify_token (JWT enabled).
- Makefile contains db-migrate AND test-benchmarks.
- .env.example does NOT contain JWT_SECRET= (RS256 path uses JWKS, not a secret).
"""
from __future__ import annotations

import ast
import re
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.e2e.conftest import FORBIDDEN_STRINGS, render_yaml_to_dict

FULL_YAML = Path(__file__).parent.parent.parent / "examples" / "project.full.yaml"
MINIMAL_YAML = Path(__file__).parent.parent / "fixtures" / "minimal.yaml"

# Files expected in the rendered output for the maximalist config.
EXPECTED_FILES = [
    # Core always-rendered files
    ".env.example",
    ".gitignore",
    "Makefile",
    "README.md",
    "requirements.txt",
    "backend/__init__.py",
    "backend/main.py",
    "backend/mcp_server.py",
    "backend/agents/__init__.py",
    "backend/agents/base_agent.py",
    "backend/agents/registry.py",
    "backend/agents/data_agent.py",
    "backend/agents/analytics_agent.py",
    "backend/graph/__init__.py",
    "backend/graph/state.py",
    "backend/graph/workflow.py",
    "backend/graph/nodes/__init__.py",
    "backend/graph/nodes/answer_node.py",
    "backend/graph/nodes/feedback_node.py",
    "backend/graph/nodes/query_router_node.py",
    "backend/graph/nodes/supervisor_node.py",
    "backend/graph/nodes/validation_node.py",
    "backend/observability/__init__.py",
    "backend/observability/logging.py",
    "backend/observability/tracing.py",
    "backend/middleware/__init__.py",
    "backend/middleware/logging_middleware.py",
    "backend/security/__init__.py",
    "backend/security/sanitizer.py",
    # TODO-1: Alembic
    "alembic.ini",
    "backend/migrations/env.py",
    "backend/migrations/script.py.mako",
    # TODO-2: GitHub CI
    ".github/workflows/ci.yml",
    # TODO-3: pre-commit
    ".pre-commit-config.yaml",
    # TODO-5: Makefile (always rendered, checked above)
    # TODO-6: MCP client
    "backend/services/__init__.py",
    "backend/services/mcp_client.py",
    # TODO-7: DeepEval benchmarks
    "backend/tests/__init__.py",
    "backend/tests/benchmarks/__init__.py",
    "backend/tests/benchmarks/conftest.py",
    "backend/tests/benchmarks/datasets.py",
    "backend/tests/benchmarks/generators.py",
    "backend/tests/benchmarks/report_plugin.py",
    "backend/tests/benchmarks/runner.py",
    "backend/tests/benchmarks/test_graph_agent.py",
    "backend/tests/benchmarks/trigger_command.py",
    "backend/tests/benchmarks/utils.py",
    # TODO-8: JWT auth
    "backend/security/jwt.py",
    "backend/security/dtos.py",
    "backend/security/jwt_settings.py",
    # TODO-9: LangGraph checkpointing
    "backend/config/__init__.py",
    "backend/config/memory_settings.py",
    "backend/graph/checkpointer.py",
]

REQUIRED_REQUIREMENTS = [
    "pyjwt",
    "deepeval",
    "langchain-mcp-adapters",
    "langgraph-checkpoint-postgres",
    "psycopg",
    "alembic",
]


@pytest.fixture(scope="module")
def scaffold() -> Iterator[dict[str, str]]:
    with tempfile.TemporaryDirectory(prefix="agentforge_e2e_") as tmpdir_str:
        yield render_yaml_to_dict(FULL_YAML, Path(tmpdir_str))


@pytest.fixture(scope="module")
def scaffold_no_mcp() -> Iterator[dict[str, str]]:
    with tempfile.TemporaryDirectory(prefix="agentforge_e2e_no_mcp_") as tmpdir_str:
        yield render_yaml_to_dict(MINIMAL_YAML, Path(tmpdir_str))


def test_expected_files_present(scaffold: dict[str, str]) -> None:
    """Every file listed in EXPECTED_FILES must be present in the rendered output."""
    missing = [f for f in EXPECTED_FILES if f not in scaffold]
    assert not missing, f"Expected files missing from scaffold: {missing}"


def test_all_py_files_parse(scaffold: dict[str, str]) -> None:
    """Every generated .py file must be valid Python (catches syntax errors)."""
    failures: list[str] = []
    for rel_path, content in scaffold.items():
        if not rel_path.endswith(".py"):
            continue
        try:
            ast.parse(content)
        except SyntaxError as exc:
            failures.append(f"{rel_path}: {exc}")
    assert not failures, "Generated .py files with syntax errors:\n" + "\n".join(failures)


def test_no_forbidden_strings(scaffold: dict[str, str]) -> None:
    """No generated file may contain madgicx, slack, or webhook (case-insensitive)."""
    violations: list[str] = []
    for rel_path, content in scaffold.items():
        for forbidden in FORBIDDEN_STRINGS:
            if re.search(forbidden, content, re.IGNORECASE):
                violations.append(f"{rel_path} contains '{forbidden}'")
    assert not violations, "Forbidden strings found in scaffold:\n" + "\n".join(violations)


def test_requirements_contains_expected_packages(scaffold: dict[str, str]) -> None:
    """requirements.txt must list all packages needed for the full-feature scaffold."""
    req = scaffold.get("requirements.txt", "")
    missing = [pkg for pkg in REQUIRED_REQUIREMENTS if pkg not in req]
    assert not missing, f"requirements.txt is missing packages: {missing}"


def test_main_py_imports_verify_token(scaffold: dict[str, str]) -> None:
    """backend/main.py must import verify_token when auth_type=jwt."""
    main_py = scaffold.get("backend/main.py", "")
    assert "verify_token" in main_py, (
        "backend/main.py does not import verify_token; "
        "expected because auth_type=jwt in project.full.yaml"
    )


def test_makefile_has_db_migrate_and_test_benchmarks(scaffold: dict[str, str]) -> None:
    """Makefile must contain db-migrate (use_alembic) and test-benchmarks (enable_benchmarks)."""
    makefile = scaffold.get("Makefile", "")
    assert "db-migrate" in makefile, "Makefile missing db-migrate target (use_alembic=true)"
    assert "test-benchmarks" in makefile, (
        "Makefile missing test-benchmarks target (enable_benchmarks=true)"
    )


def test_env_example_no_jwt_secret_for_rs256(scaffold: dict[str, str]) -> None:
    """RS256 path must NOT emit JWT_SECRET= in .env.example (that is only for HS256)."""
    env_example = scaffold.get(".env.example", "")
    assert "JWT_SECRET=" not in env_example, (
        ".env.example contains JWT_SECRET= but the config uses RS256 (JWKS). "
        "JWT_SECRET is only required for HS256."
    )


def test_mcp_client_uses_env_var_not_dead_settings_import(scaffold: dict[str, str]) -> None:
    """mcp_client.py must read from MCP_SERVERS env var, not a dead settings import."""
    mcp = scaffold.get("backend/services/mcp_client.py", "")
    assert "MCP_SERVERS" in mcp
    assert "backend.config.settings" not in mcp  # regression guard


def test_mcp_client_imports_use_backend_prefix(scaffold: dict[str, str]) -> None:
    """mcp_client.py must use fully-qualified backend.* imports, not bare top-level ones."""
    mcp = scaffold.get("backend/services/mcp_client.py", "")
    assert "\nfrom observability." not in mcp
    assert "\nfrom services." not in mcp
    assert "from backend.observability" in mcp


def test_env_example_documents_mcp_vars_when_mcp_enabled(scaffold: dict[str, str]) -> None:
    """When MCP is enabled, .env.example must document MCP_SERVERS and MCP_TIMEOUT."""
    env = scaffold.get(".env.example", "")
    assert "MCP_SERVERS" in env
    assert "MCP_TIMEOUT" in env


def test_env_example_omits_mcp_vars_when_mcp_disabled(
    scaffold_no_mcp: dict[str, str],
) -> None:
    """When no agent tool uses mcp_resource, .env.example must NOT contain MCP_SERVERS."""
    env = scaffold_no_mcp.get(".env.example", "")
    assert "MCP_SERVERS" not in env, (
        ".env.example documents MCP_SERVERS even though no MCP tools are configured"
    )
