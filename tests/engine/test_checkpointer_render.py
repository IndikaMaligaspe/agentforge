"""
Tests for LangGraph PostgresSaver checkpointing scaffold rendering (TODO-9).

Covers:
- No checkpointing files rendered when enable_checkpointing=False.
- Both checkpointing files rendered when enable_checkpointing=True + postgres.
- Rendered checkpointer.py compiles (no syntax errors).
- Graph builder (workflow.py) emits checkpointer= only when enabled.
- pyproject.toml includes langgraph-checkpoint-postgres and psycopg[binary,pool]
  only when checkpointing is enabled.
"""
import ast
import re

import pytest

from agentforge.schema.models import (
    AgentConfig,
    DatabaseConfig,
    DBBackend,
    LLMModel,
    ProjectConfig,
    ProjectMetadata,
    WorkflowConfig,
)
from agentforge.engine.renderer import TemplateRenderer


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_config(enable_checkpointing: bool, backend: str = "postgres") -> ProjectConfig:
    """Build a minimal valid ProjectConfig for checkpointing tests."""
    return ProjectConfig(
        metadata=ProjectMetadata(
            name="test_project",
            description="Checkpointer render test",
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
        database=DatabaseConfig(
            backend=DBBackend(backend),
            connection_env_var="DATABASE_URL",
            pool_size=5,
            max_overflow=10,
            use_alembic=False,
        ),
        workflow=WorkflowConfig(default_intent="sql", enable_checkpointing=enable_checkpointing),  # type: ignore[call-arg]
        enable_provider_registry=False,
    )


def _render_map(config: ProjectConfig) -> dict[str, str]:
    """Render all templates and return a {relative_path: content} mapping."""
    renderer = TemplateRenderer()
    return {str(path): content for path, content in renderer.render_all(config)}


CHECKPOINTER_PATHS = {
    "backend/graph/checkpointer.py",
    "backend/config/memory_settings.py",
    "backend/config/__init__.py",
}


# ── Disabled path — zero memory artifacts ─────────────────────────────────────

def test_checkpointer_files_absent_when_disabled():
    """No checkpointing files must appear when enable_checkpointing=False."""
    rendered = _render_map(_make_config(enable_checkpointing=False))
    for path in CHECKPOINTER_PATHS:
        assert path not in rendered, (
            f"Unexpected file '{path}' rendered with enable_checkpointing=False"
        )


def test_workflow_no_checkpointer_import_when_disabled():
    """workflow.py must not import from .checkpointer when checkpointing is disabled."""
    rendered = _render_map(_make_config(enable_checkpointing=False))
    workflow_content = rendered["backend/graph/workflow.py"]
    assert "checkpointer" not in workflow_content
    assert "get_postgres_saver" not in workflow_content


def test_pyproject_no_checkpoint_deps_when_disabled():
    """pyproject.toml must not list checkpoint deps when disabled."""
    renderer = TemplateRenderer()
    config = _make_config(enable_checkpointing=False)
    ctx = renderer._build_context(config)
    tmpl = renderer._env.get_template("pyproject.toml.j2")
    content = tmpl.render(**ctx)
    assert "langgraph-checkpoint-postgres" not in content
    # psycopg[binary,pool] (the pool variant) must be absent
    assert "psycopg[binary,pool]" not in content


# ── Enabled path — both files rendered ───────────────────────────────────────

def test_checkpointer_files_present_when_enabled():
    """Both checkpointing files must appear when enable_checkpointing=True."""
    rendered = _render_map(_make_config(enable_checkpointing=True))
    assert "backend/graph/checkpointer.py" in rendered, (
        "backend/graph/checkpointer.py missing when enable_checkpointing=True"
    )
    assert "backend/config/memory_settings.py" in rendered, (
        "backend/config/memory_settings.py missing when enable_checkpointing=True"
    )


def test_config_init_present_when_checkpointing_enabled():
    """backend/config/__init__.py must be emitted when checkpointing is enabled."""
    rendered = _render_map(_make_config(enable_checkpointing=True))
    assert "backend/config/__init__.py" in rendered


# ── Rendered checkpointer.py compiles ────────────────────────────────────────

def test_checkpointer_py_compiles():
    """Rendered checkpointer.py must be valid Python (parse with ast)."""
    rendered = _render_map(_make_config(enable_checkpointing=True))
    source = rendered["backend/graph/checkpointer.py"]
    # ast.parse raises SyntaxError on invalid Python — that is the assertion.
    try:
        ast.parse(source)
    except SyntaxError as exc:
        pytest.fail(f"checkpointer.py has a syntax error: {exc}\n\nSource:\n{source}")


def test_memory_settings_py_compiles():
    """Rendered memory_settings.py must be valid Python (parse with ast)."""
    rendered = _render_map(_make_config(enable_checkpointing=True))
    source = rendered["backend/config/memory_settings.py"]
    try:
        ast.parse(source)
    except SyntaxError as exc:
        pytest.fail(f"memory_settings.py has a syntax error: {exc}\n\nSource:\n{source}")


# ── checkpointer.py content ───────────────────────────────────────────────────

def test_checkpointer_imports_from_memory_settings():
    """checkpointer.py must import DATABASE_URL from backend.config.memory_settings."""
    rendered = _render_map(_make_config(enable_checkpointing=True))
    content = rendered["backend/graph/checkpointer.py"]
    assert "from backend.config.memory_settings import DATABASE_URL" in content


def test_checkpointer_uses_async_postgres_saver():
    """checkpointer.py must use AsyncPostgresSaver."""
    rendered = _render_map(_make_config(enable_checkpointing=True))
    content = rendered["backend/graph/checkpointer.py"]
    assert "AsyncPostgresSaver" in content


def test_checkpointer_exposes_get_checkpointer():
    """checkpointer.py must expose get_checkpointer()."""
    rendered = _render_map(_make_config(enable_checkpointing=True))
    content = rendered["backend/graph/checkpointer.py"]
    assert "def get_checkpointer" in content


def test_checkpointer_exposes_init_checkpointer():
    """checkpointer.py must expose async init_checkpointer()."""
    rendered = _render_map(_make_config(enable_checkpointing=True))
    content = rendered["backend/graph/checkpointer.py"]
    assert "async def init_checkpointer" in content


def test_checkpointer_exposes_aclose_checkpointer():
    """checkpointer.py must expose async aclose_checkpointer()."""
    rendered = _render_map(_make_config(enable_checkpointing=True))
    content = rendered["backend/graph/checkpointer.py"]
    assert "async def aclose_checkpointer" in content


# ── memory_settings.py content ────────────────────────────────────────────────

def test_memory_settings_uses_database_url_env_var():
    """memory_settings.py must read from DATABASE_URL environment variable."""
    rendered = _render_map(_make_config(enable_checkpointing=True))
    content = rendered["backend/config/memory_settings.py"]
    assert "DATABASE_URL" in content
    assert "os.environ" in content


def test_memory_settings_no_madgicx_references():
    """memory_settings.py must contain no references to 'madgicx' or 'app.core'."""
    rendered = _render_map(_make_config(enable_checkpointing=True))
    content = rendered["backend/config/memory_settings.py"]
    assert "madgicx" not in content.lower()
    assert "app.core" not in content


# ── workflow.py with checkpointing enabled ────────────────────────────────────

def test_workflow_imports_checkpointer_symbols_when_enabled():
    """workflow.py must import init_checkpointer, aclose_checkpointer, get_checkpointer when enabled."""
    rendered = _render_map(_make_config(enable_checkpointing=True))
    workflow_content = rendered["backend/graph/workflow.py"]
    assert "from .checkpointer import" in workflow_content
    assert "init_checkpointer" in workflow_content
    assert "aclose_checkpointer" in workflow_content
    assert "get_checkpointer" in workflow_content


def test_workflow_get_compiled_graph_uses_checkpointer_when_enabled():
    """workflow.py must call get_checkpointer() inside get_compiled_graph() when enabled."""
    rendered = _render_map(_make_config(enable_checkpointing=True))
    workflow_content = rendered["backend/graph/workflow.py"]
    assert "get_compiled_graph" in workflow_content
    assert "get_checkpointer()" in workflow_content


def test_workflow_compile_no_checkpointer_when_disabled():
    """workflow.py must call .compile() without checkpointer= when disabled."""
    rendered = _render_map(_make_config(enable_checkpointing=False))
    workflow_content = rendered["backend/graph/workflow.py"]
    assert "compile()" in workflow_content
    assert "checkpointer" not in workflow_content


# ── pyproject.toml with checkpointing enabled ─────────────────────────────────

def test_pyproject_includes_checkpoint_deps_when_enabled():
    """pyproject.toml must list langgraph-checkpoint-postgres and psycopg[binary,pool] when enabled."""
    renderer = TemplateRenderer()
    config = _make_config(enable_checkpointing=True)
    ctx = renderer._build_context(config)
    tmpl = renderer._env.get_template("pyproject.toml.j2")
    content = tmpl.render(**ctx)
    assert "langgraph-checkpoint-postgres" in content
    assert "psycopg[binary,pool]" in content


def test_pyproject_checkpoint_dep_pins():
    """langgraph-checkpoint-postgres must be pinned >=2.0.0,<3.0.0."""
    renderer = TemplateRenderer()
    config = _make_config(enable_checkpointing=True)
    ctx = renderer._build_context(config)
    tmpl = renderer._env.get_template("pyproject.toml.j2")
    content = tmpl.render(**ctx)
    assert ">=2.0.0,<3.0.0" in content


def test_pyproject_psycopg_pool_pin():
    """psycopg[binary,pool] must be pinned >=3.2.0,<4.0.0."""
    renderer = TemplateRenderer()
    config = _make_config(enable_checkpointing=True)
    ctx = renderer._build_context(config)
    tmpl = renderer._env.get_template("pyproject.toml.j2")
    content = tmpl.render(**ctx)
    assert ">=3.2.0,<4.0.0" in content


# ── Fix 1: pool-based async pattern (no from_conn_string) ────────────────────

def test_checkpointer_uses_async_pool_pattern():
    """checkpointer.py must use AsyncConnectionPool + async init, not from_conn_string."""
    rendered = _render_map(_make_config(enable_checkpointing=True))
    content = rendered["backend/graph/checkpointer.py"]
    assert "AsyncConnectionPool" in content
    assert "init_checkpointer" in content
    assert "aclose_checkpointer" in content
    assert "from_conn_string" not in content


# ── Fix 3: DSN scheme ─────────────────────────────────────────────────────────

def test_dsn_uses_plain_postgresql_scheme():
    """memory_settings.py default DSN must use postgresql:// not postgresql+psycopg://."""
    rendered = _render_map(_make_config(enable_checkpointing=True))
    content = rendered["backend/config/memory_settings.py"]
    assert "postgresql://" in content
    assert "postgresql+psycopg://" not in content


# ── Fix 2: no top-level get_checkpointer() call at import time ───────────────

def test_workflow_template_does_not_call_saver_at_import():
    """workflow.py with checkpointing enabled must not call get_checkpointer() at module top level."""
    rendered = _render_map(_make_config(enable_checkpointing=True))
    content = rendered["backend/graph/workflow.py"]

    # Parse the module; find all calls to get_checkpointer at module scope
    # (i.e., not inside a function or class body).
    tree = ast.parse(content)
    top_level_calls = []
    for node in ast.iter_child_nodes(tree):
        # Only look at top-level expressions and assignments outside functions
        if isinstance(node, (ast.Expr, ast.Assign, ast.AugAssign, ast.AnnAssign)):
            for child in ast.walk(node):
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Name)
                    and child.func.id == "get_checkpointer"
                ):
                    top_level_calls.append(child)

    assert not top_level_calls, (
        "get_checkpointer() must not be called at module top level in workflow.py; "
        f"found {len(top_level_calls)} top-level call(s)"
    )
