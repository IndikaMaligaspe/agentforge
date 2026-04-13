"""
Tests for MCP client scaffold rendering (TODO-6).

Covers:
- File NOT rendered when no agent tool has mcp_resource set (predicate false).
- File rendered when at least one agent tool has mcp_resource set (predicate true).
- Rendered file contains the required import statements.
- Rendered file is syntactically valid Python (compile check).
- pyproject.toml includes langchain-mcp-adapters only when has_mcp is True.
"""
from pathlib import Path

import pytest

from agentforge.engine.renderer import TemplateRenderer
from agentforge.schema.loader import load
from agentforge.schema.models import (
    AgentConfig,
    LLMModel,
    ProjectConfig,
    ProjectMetadata,
    ToolConfig,
    WorkflowConfig,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"

MCP_OUTPUT_PATH = "backend/services/mcp_client.py"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _render_map(config: ProjectConfig) -> dict[str, str]:
    """Render all templates and return a {relative_path: content} mapping."""
    renderer = TemplateRenderer()
    return {str(path): content for path, content in renderer.render_all(config)}


def _render_pyproject(config: ProjectConfig) -> str:
    """Render pyproject.toml.j2 directly (it is not in STATIC_TEMPLATE_MAP)."""
    renderer = TemplateRenderer()
    ctx = renderer._build_context(config)
    tmpl = renderer._env.get_template("pyproject.toml.j2")
    return tmpl.render(**ctx)


def _make_config_no_mcp() -> ProjectConfig:
    """Minimal config: one agent with no tools — predicate must be false."""
    return ProjectConfig(
        metadata=ProjectMetadata(
            name="no_mcp_project",
            description="Project with no MCP tools",
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
    )


def _make_config_with_mcp() -> ProjectConfig:
    """Config with one agent that has a tool with mcp_resource — predicate must be true."""
    return ProjectConfig(
        metadata=ProjectMetadata(
            name="mcp_project",
            description="Project with MCP tools",
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
                tools=[
                    ToolConfig(
                        name="execute_sql",
                        description="Run a SQL query",
                        mcp_resource="foo",
                    )
                ],
            )
        ],
        workflow=WorkflowConfig(default_intent="sql"),  # type: ignore[call-arg]
    )


# ── Predicate false ───────────────────────────────────────────────────────────

def test_mcp_file_absent_when_no_tool_has_mcp_resource():
    """No MCP client file must be emitted when no tool sets mcp_resource."""
    rendered = _render_map(_make_config_no_mcp())
    assert MCP_OUTPUT_PATH not in rendered


def test_mcp_file_absent_when_tool_mcp_resource_is_none():
    """mcp_resource=None (explicit) must also leave the predicate false."""
    config = ProjectConfig(
        metadata=ProjectMetadata(
            name="none_mcp_project",
            description="mcp_resource explicitly None",
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
                tools=[
                    ToolConfig(
                        name="plain_tool",
                        description="A tool without MCP",
                        mcp_resource=None,
                    )
                ],
            )
        ],
        workflow=WorkflowConfig(default_intent="sql"),  # type: ignore[call-arg]
    )
    rendered = _render_map(config)
    assert MCP_OUTPUT_PATH not in rendered


# ── Predicate true ────────────────────────────────────────────────────────────

def test_mcp_file_present_when_tool_has_mcp_resource():
    """MCP client file must be emitted when at least one tool has mcp_resource set."""
    rendered = _render_map(_make_config_with_mcp())
    assert MCP_OUTPUT_PATH in rendered


def test_mcp_file_present_using_full_fixture():
    """full.yaml already has mcp_resource on every tool — file must be rendered."""
    config = load(FIXTURES_DIR / "full.yaml")
    rendered = _render_map(config)
    assert MCP_OUTPUT_PATH in rendered


# ── Import statements ─────────────────────────────────────────────────────────

def test_rendered_file_contains_multiservermcpclient_import():
    """Rendered MCP client must import MultiServerMCPClient."""
    rendered = _render_map(_make_config_with_mcp())
    content = rendered[MCP_OUTPUT_PATH]
    assert "MultiServerMCPClient" in content


def test_rendered_file_contains_streamablehttpconnection_import():
    """Rendered MCP client must import StreamableHttpConnection."""
    rendered = _render_map(_make_config_with_mcp())
    content = rendered[MCP_OUTPUT_PATH]
    assert "StreamableHttpConnection" in content


def test_rendered_file_imports_from_langchain_mcp_adapters():
    """Both classes must come from langchain_mcp_adapters.client."""
    rendered = _render_map(_make_config_with_mcp())
    content = rendered[MCP_OUTPUT_PATH]
    assert "from langchain_mcp_adapters.client import" in content


# ── Syntax validity ───────────────────────────────────────────────────────────

def test_rendered_file_is_valid_python():
    """Rendered MCP client must be syntactically valid Python."""
    rendered = _render_map(_make_config_with_mcp())
    source = rendered[MCP_OUTPUT_PATH]
    # compile() raises SyntaxError for invalid Python
    compile(source, MCP_OUTPUT_PATH, "exec")


# ── pyproject.toml conditional dependency ────────────────────────────────────

def test_pyproject_includes_langchain_mcp_adapters_when_has_mcp():
    """pyproject.toml must list langchain-mcp-adapters when has_mcp is True."""
    content = _render_pyproject(_make_config_with_mcp())
    assert "langchain-mcp-adapters" in content


def test_pyproject_excludes_langchain_mcp_adapters_when_no_mcp():
    """pyproject.toml must NOT list langchain-mcp-adapters when has_mcp is False."""
    content = _render_pyproject(_make_config_no_mcp())
    assert "langchain-mcp-adapters" not in content
