"""
Tests for the template rendering engine.
"""
from pathlib import Path
import pytest

from agentforge.schema.loader import load
from agentforge.engine.renderer import TemplateRenderer
from agentforge.schema.models import AgentConfig, ToolConfig, LLMModel

FIXTURES_DIR = Path(__file__).parent / "fixtures"

def test_render_all():
    """Test rendering all templates for a project."""
    config = load(FIXTURES_DIR / "minimal.yaml")
    renderer = TemplateRenderer()
    
    rendered_files = renderer.render_all(config)
    
    # Check that we got the expected number of files
    assert len(rendered_files) > 0
    
    # Check that the files include the expected paths
    paths = [str(path) for path, _ in rendered_files]
    assert "backend/agents/base_agent.py" in paths
    assert "backend/agents/registry.py" in paths
    assert "backend/agents/sql_agent.py" in paths
    
    # Check content of a specific file
    for path, content in rendered_files:
        if str(path) == "backend/agents/sql_agent.py":
            # Check that the agent key and class name are correctly rendered
            assert "SQLAgent" in content
            assert "sql" in content
            assert "You are a SQL assistant" in content

def test_render_agent():
    """Test rendering a single agent."""
    config = load(FIXTURES_DIR / "minimal.yaml")
    renderer = TemplateRenderer()
    
    # Create a new agent config
    new_agent = AgentConfig(
        key="analytics",
        class_name="AnalyticsAgent",
        llm_model=LLMModel.GPT4O_MINI,
        system_prompt="You are an analytics assistant.",
        tools=[
            ToolConfig(
                name="analyze_data",
                description="Run analysis on data",
            )
        ]
    )
    
    rendered_files = renderer.render_agent(new_agent, config)
    
    # Should return the agent file and the updated registry
    assert len(rendered_files) == 2
    
    paths = [str(path) for path, _ in rendered_files]
    assert "backend/agents/analytics_agent.py" in paths
    assert "backend/agents/registry.py" in paths
    
    # Check content
    for path, content in rendered_files:
        if str(path) == "backend/agents/analytics_agent.py":
            assert "AnalyticsAgent" in content
            assert "analytics" in content
            assert "You are an analytics assistant" in content
            assert "analyze_data" in content

def test_build_context():
    """Test the context building for templates."""
    config = load(FIXTURES_DIR / "full.yaml")
    renderer = TemplateRenderer()
    
    # Access the private method for testing
    context = renderer._build_context(config)
    
    # Check that the context contains the expected keys
    assert "project_name" in context
    assert "agents_list" in context
    assert "agent_keys" in context
    assert "valid_intents" in context
    assert "default_intent" in context
    assert "enable_feedback_loop" in context
    assert "enable_validation_node" in context
    assert "enable_tracing" in context
    assert "enable_auth" in context
    
    # Check specific values
    assert context["project_name"] == "full_featured_project"
    assert len(context["agents_list"]) == 2
    assert context["agent_keys"] == ["sql", "analytics"]
    assert context["valid_intents"] == ["sql", "analytics"]
    assert context["default_intent"] == "sql"
    assert context["enable_feedback_loop"] is True
    assert context["enable_validation_node"] is True
    assert context["enable_tracing"] is True
    assert context["enable_auth"] is True