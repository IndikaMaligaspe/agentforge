"""
Tests for the Pydantic schema models.
"""
import pytest
from pydantic import ValidationError

from agentforge.schema.models import (
    ProjectConfig, ProjectMetadata, AgentConfig, 
    ToolConfig, LLMModel, DBBackend
)

def test_valid_minimal_config():
    """Test a minimal valid configuration."""
    config = ProjectConfig(
        metadata=ProjectMetadata(
            name="test_project",
            description="Test project",
            python_version="3.11",
            author="Test Author",
            email="test@example.com",
        ),
        agents=[
            AgentConfig(
                key="sql",
                class_name="SQLAgent",
                llm_model=LLMModel.GPT4O_MINI,
                system_prompt="You are a SQL assistant.",
            )
        ],
        workflow={"default_intent": "sql"}
    )
    
    assert config.metadata.name == "test_project"
    assert len(config.agents) == 1
    assert config.agents[0].key == "sql"
    assert config.workflow.default_intent == "sql"

def test_invalid_agent_key():
    """Test that reserved agent keys are rejected."""
    with pytest.raises(ValidationError) as exc_info:
        AgentConfig(
            key="base",  # reserved key
            class_name="BaseAgent",
            llm_model=LLMModel.GPT4O_MINI,
        )
    
    assert "Agent key 'base' is reserved" in str(exc_info.value)

def test_default_intent_validation():
    """Test that default_intent must be a registered agent key."""
    with pytest.raises(ValidationError) as exc_info:
        ProjectConfig(
            metadata=ProjectMetadata(
                name="test_project",
                description="Test project",
                python_version="3.11",
                author="Test Author",
                email="test@example.com",
            ),
            agents=[
                AgentConfig(
                    key="sql",
                    class_name="SQLAgent",
                    llm_model=LLMModel.GPT4O_MINI,
                )
            ],
            workflow={"default_intent": "nonexistent"}  # not a registered agent key
        )
    
    assert "default_intent='nonexistent' is not in agents keys" in str(exc_info.value)

def test_validation_node_consistency():
    """Test that if any agent needs validation, enable_validation_node must be True."""
    with pytest.raises(ValidationError) as exc_info:
        ProjectConfig(
            metadata=ProjectMetadata(
                name="test_project",
                description="Test project",
                python_version="3.11",
                author="Test Author",
                email="test@example.com",
            ),
            agents=[
                AgentConfig(
                    key="sql",
                    class_name="SQLAgent",
                    llm_model=LLMModel.GPT4O_MINI,
                    needs_validation=True,
                )
            ],
            workflow={
                "default_intent": "sql",
                "enable_validation_node": False,  # inconsistent with needs_validation=True
            }
        )
    
    assert "workflow.enable_validation_node must be True" in str(exc_info.value)