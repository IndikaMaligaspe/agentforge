"""
Tests for the Pydantic schema models.
"""
import pytest
from pydantic import ValidationError

from agentforge.schema.models import (
    ProjectConfig, ProjectMetadata, AgentConfig,
    ToolConfig, LLMModel, DBBackend, WorkflowConfig, ObservabilityConfig,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _minimal_config(**overrides):
    """Return a minimal valid ProjectConfig, applying any overrides at the top level."""
    base = dict(
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
        workflow={"default_intent": "sql"},
    )
    base.update(overrides)
    return ProjectConfig(**base)


# ── Existing tests ────────────────────────────────────────────────────────────

def test_valid_minimal_config():
    """Test a minimal valid configuration."""
    config = _minimal_config()

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


# ── TODO-2 new tests ──────────────────────────────────────────────────────────

def test_structured_logging_defaults_false():
    """ObservabilityConfig.structured_logging must default to False."""
    obs = ObservabilityConfig()
    assert obs.structured_logging is False


def test_router_llm_provider_defaults_openai():
    """WorkflowConfig.router_llm_provider must default to 'openai'."""
    wf = WorkflowConfig()
    assert wf.router_llm_provider == "openai"


def test_enable_provider_registry_defaults_false():
    """ProjectConfig.enable_provider_registry must default to False."""
    config = _minimal_config()
    assert config.enable_provider_registry is False


def test_router_llm_provider_invalid_value():
    """An unsupported router_llm_provider value must raise ValidationError."""
    with pytest.raises(ValidationError):
        WorkflowConfig(router_llm_provider="gemini")  # type: ignore[arg-type]


def test_provider_model_mismatch_warns_but_validates():
    """
    Mismatched router_llm_provider / router_llm_model should trigger a UserWarning
    but must NOT raise — validation must succeed.
    """
    with pytest.warns(UserWarning, match="likely a misconfiguration"):
        wf = WorkflowConfig(
            router_llm_provider="anthropic",
            router_llm_model=LLMModel.GPT4O_MINI,  # gpt- model with anthropic provider
            default_intent="sql",
        )
    # Validation succeeded — object is usable.
    assert wf.router_llm_provider == "anthropic"
    assert wf.router_llm_model == LLMModel.GPT4O_MINI


def test_project_yaml_omitting_new_flags_validates_with_defaults():
    """
    A project.yaml that omits all three new flags must validate without error
    and the fields must carry their correct defaults.
    """
    config = _minimal_config()  # none of the three new flags are supplied
    assert config.observability.structured_logging is False
    assert config.workflow.router_llm_provider == "openai"
    assert config.enable_provider_registry is False
