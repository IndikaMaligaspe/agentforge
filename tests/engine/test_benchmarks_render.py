"""
Tests for DeepEval benchmark scaffold rendering (TODO-7).

Covers:
- No benchmark files rendered when enable_benchmarks=False (default).
- No benchmark files rendered when eval_framework="none" (schema rejects this combo anyway).
- All benchmark files rendered under backend/tests/benchmarks/ when
  eval_framework="deepeval" and enable_benchmarks=True.
- Rendered conftest.py compiles (ast.parse).
- Each rendered benchmark Python file compiles.
- No "slack" or "webhook" substring anywhere in rendered output (case-insensitive).
- requirements.txt includes deepeval only when benchmarks enabled.
"""
import ast
import re

import pytest

from typing import Literal

from agentforge.schema.models import (
    AgentConfig,
    LLMModel,
    ProjectConfig,
    ProjectMetadata,
    TestingConfig,
    WorkflowConfig,
)
from agentforge.engine.renderer import TemplateRenderer


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_config(
    eval_framework: Literal["none", "deepeval"] = "none",
    enable_benchmarks: bool = False,
) -> ProjectConfig:
    """Build a minimal valid ProjectConfig with the given testing settings."""
    return ProjectConfig(
        metadata=ProjectMetadata(
            name="test_project",
            description="Benchmark render test",
            python_version="3.11",
            author="Test Author",
            email="test@example.com",
        ),
        agents=[
            AgentConfig(
                key="sql",
                class_name="SqlAgent",
                llm_model=LLMModel.GPT4O_MINI,
                system_prompt="You are a helpful assistant.",
                needs_validation=False,
            )
        ],
        workflow=WorkflowConfig(default_intent="sql"),  # type: ignore[call-arg]
        testing=TestingConfig(  # type: ignore[call-arg]
            eval_framework=eval_framework,
            enable_benchmarks=enable_benchmarks,
        ),
        enable_provider_registry=False,
    )


def _render_map(config: ProjectConfig) -> dict[str, str]:
    """Render all templates and return a {relative_path: content} mapping."""
    renderer = TemplateRenderer()
    return {str(path): content for path, content in renderer.render_all(config)}


# Expected benchmark output paths
BENCHMARK_PATHS = [
    "backend/tests/benchmarks/__init__.py",
    "backend/tests/benchmarks/conftest.py",
    "backend/tests/benchmarks/datasets.py",
    "backend/tests/benchmarks/generators.py",
    "backend/tests/benchmarks/report_plugin.py",
    "backend/tests/benchmarks/runner.py",
    "backend/tests/benchmarks/test_graph_agent.py",
    "backend/tests/benchmarks/trigger_command.py",
    "backend/tests/benchmarks/utils.py",
    "backend/tests/benchmarks/base_mcp_mocks.json",
]


# ── Schema defaults ───────────────────────────────────────────────────────────

def test_testing_config_defaults():
    """TestingConfig must default to eval_framework=none and enable_benchmarks=False."""
    cfg = TestingConfig()  # type: ignore[call-arg]
    assert cfg.eval_framework == "none"
    assert cfg.enable_benchmarks is False


def test_project_config_testing_defaults():
    """ProjectConfig.testing must default so existing projects are unaffected."""
    config = _make_config()
    assert config.testing.eval_framework == "none"
    assert config.testing.enable_benchmarks is False


# ── Disabled path — no benchmark artifacts ────────────────────────────────────

def test_no_benchmark_files_when_disabled_default():
    """Default config (enable_benchmarks=False) must emit zero benchmark files."""
    rendered = _render_map(_make_config())
    for path in BENCHMARK_PATHS:
        assert path not in rendered, f"Expected {path} absent but it was rendered"


def test_no_benchmark_files_when_framework_none_benchmarks_false():
    """eval_framework=none + enable_benchmarks=False must emit zero benchmark files."""
    rendered = _render_map(_make_config(eval_framework="none", enable_benchmarks=False))
    for path in BENCHMARK_PATHS:
        assert path not in rendered, f"Expected {path} absent but it was rendered"


def test_no_benchmark_files_when_framework_deepeval_benchmarks_false():
    """eval_framework=deepeval + enable_benchmarks=False must emit zero benchmark files."""
    rendered = _render_map(_make_config(eval_framework="deepeval", enable_benchmarks=False))
    for path in BENCHMARK_PATHS:
        assert path not in rendered, f"Expected {path} absent but it was rendered"


# ── Enabled path — all benchmark files rendered ───────────────────────────────

def test_all_benchmark_files_rendered_when_enabled():
    """All benchmark files must be rendered when eval_framework=deepeval and enable_benchmarks=True."""
    rendered = _render_map(_make_config(eval_framework="deepeval", enable_benchmarks=True))
    for path in BENCHMARK_PATHS:
        assert path in rendered, f"Expected {path} in rendered output but it was absent"


# ── Compilability of Python benchmark files ───────────────────────────────────

BENCHMARK_PY_PATHS = [p for p in BENCHMARK_PATHS if p.endswith(".py")]


@pytest.mark.parametrize("path", BENCHMARK_PY_PATHS)
def test_benchmark_python_file_compiles(path: str):
    """Every rendered benchmark Python file must be valid Python (ast.parse)."""
    rendered = _render_map(_make_config(eval_framework="deepeval", enable_benchmarks=True))
    assert path in rendered, f"{path} was not rendered"
    content = rendered[path]
    try:
        ast.parse(content)
    except SyntaxError as e:
        pytest.fail(f"{path} has a syntax error: {e}")


# ── No Slack / webhook references anywhere in rendered output ─────────────────

def test_no_slack_references_in_rendered_output():
    """Case-insensitive grep for 'slack' must find zero matches across ALL rendered files."""
    rendered = _render_map(_make_config(eval_framework="deepeval", enable_benchmarks=True))
    violations = []
    for path, content in rendered.items():
        if re.search(r"slack", content, re.IGNORECASE):
            violations.append(path)
    assert not violations, (
        f"'slack' found (case-insensitive) in rendered files: {violations}"
    )


def test_no_webhook_references_in_rendered_output():
    """Case-insensitive grep for 'webhook' must find zero matches across ALL rendered files."""
    rendered = _render_map(_make_config(eval_framework="deepeval", enable_benchmarks=True))
    violations = []
    for path, content in rendered.items():
        if re.search(r"webhook", content, re.IGNORECASE):
            violations.append(path)
    assert not violations, (
        f"'webhook' found (case-insensitive) in rendered files: {violations}"
    )


def test_no_slack_in_disabled_output():
    """'slack' must also be absent when benchmarks are disabled."""
    rendered = _render_map(_make_config())
    for path, content in rendered.items():
        assert not re.search(r"slack", content, re.IGNORECASE), (
            f"'slack' found in {path} (benchmarks disabled)"
        )


# ── requirements.txt deepeval dependency ─────────────────────────────────────

def test_requirements_includes_deepeval_when_enabled():
    """requirements.txt must list deepeval when benchmarks are enabled."""
    rendered = _render_map(_make_config(eval_framework="deepeval", enable_benchmarks=True))
    assert "requirements.txt" in rendered
    assert "deepeval" in rendered["requirements.txt"]


def test_requirements_excludes_deepeval_when_disabled():
    """requirements.txt must NOT list deepeval when benchmarks are disabled."""
    rendered = _render_map(_make_config())
    assert "requirements.txt" in rendered
    assert "deepeval" not in rendered["requirements.txt"]


def test_requirements_excludes_deepeval_framework_only():
    """requirements.txt must NOT list deepeval when framework set but benchmarks=False."""
    rendered = _render_map(_make_config(eval_framework="deepeval", enable_benchmarks=False))
    assert "requirements.txt" in rendered
    assert "deepeval" not in rendered["requirements.txt"]


# ── Output path prefix ────────────────────────────────────────────────────────

def test_benchmark_files_under_backend_tests_benchmarks():
    """All benchmark output paths must be under backend/tests/benchmarks/."""
    rendered = _render_map(_make_config(eval_framework="deepeval", enable_benchmarks=True))
    benchmark_keys = [k for k in rendered if "benchmarks" in k]
    for path in benchmark_keys:
        assert path.startswith("backend/tests/benchmarks/"), (
            f"Benchmark file rendered to unexpected path: {path}"
        )


# ── Import rebinding — no app.services references ────────────────────────────

def test_no_app_services_imports_in_benchmark_output():
    """Rendered benchmark files must not import from app.services (old agentic-cli layout)."""
    rendered = _render_map(_make_config(eval_framework="deepeval", enable_benchmarks=True))
    for path in BENCHMARK_PY_PATHS:
        content = rendered.get(path, "")
        assert "app.services" not in content, (
            f"Old agentic-cli import 'app.services' found in {path}"
        )
        assert "app.core" not in content, (
            f"Old agentic-cli import 'app.core' found in {path}"
        )


def test_pyproject_no_pytest_markers_when_benchmarks_disabled():
    """[tool.pytest.ini_options] markers block must be absent from rendered pyproject.toml when enable_benchmarks=False.

    The pyproject.toml.j2 template is rendered directly via the Jinja environment
    because the renderer only wires it conditionally; this test validates the template
    logic itself regardless of whether the renderer emits the file.
    """
    config = _make_config(eval_framework="none", enable_benchmarks=False)
    renderer = TemplateRenderer()
    ctx = renderer._build_context(config)
    tmpl = renderer._env.get_template("pyproject.toml.j2")
    content = tmpl.render(ctx)
    assert "[tool.pytest.ini_options]" not in content, (
        "pyproject.toml must not contain [tool.pytest.ini_options] when enable_benchmarks=False"
    )
    assert "markers" not in content, (
        "pyproject.toml must not contain a markers entry when enable_benchmarks=False"
    )
