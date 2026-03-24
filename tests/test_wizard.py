"""
Tests for the interactive wizard functionality.
"""
import pytest
from unittest.mock import patch, MagicMock
from agentforge.prompts.wizard import ProjectWizard
from agentforge.schema.models import ProjectConfig

@pytest.fixture
def mock_questionary():
    """Mock questionary to simulate user input."""
    with patch("agentforge.prompts.wizard.questionary") as mock:
        yield mock

def test_wizard_initialization():
    """Test that the wizard initializes correctly."""
    wizard = ProjectWizard()
    assert wizard is not None
    assert hasattr(wizard, "run")

def test_wizard_run_minimal(mock_questionary):
    """Test running the wizard with minimal inputs."""
    # Mock the questionary responses
    mock_questionary.text.return_value.ask.side_effect = [
        "test-project",  # project name
        "A test project",  # description
        "0.1.0",  # version
    ]
    mock_questionary.confirm.return_value.ask.side_effect = [
        True,  # Use default agent
        False,  # No custom agents
        False,  # No database
        False,  # No auth
        False,  # No tracing
    ]
    mock_questionary.select.return_value.ask.side_effect = [
        "analysis",  # default intent
    ]
    
    # Run the wizard
    wizard = ProjectWizard()
    config = wizard.run()
    
    # Verify the result
    assert isinstance(config, ProjectConfig)
    assert config.metadata.name == "test-project"
    assert config.metadata.description == "A test project"
    assert config.metadata.version == "0.1.0"
    assert len(config.agents) >= 1  # Should have at least the default agent

def test_wizard_run_full(mock_questionary):
    """Test running the wizard with full configuration."""
    # Mock the questionary responses
    mock_questionary.text.return_value.ask.side_effect = [
        "full-project",  # project name
        "A full test project",  # description
        "1.0.0",  # version
        "analysis",  # agent key
        "Analysis Agent",  # agent name
        "Analyzes data",  # agent description
        "sql",  # second agent key
        "SQL Agent",  # second agent name
        "Executes SQL queries",  # second agent description
    ]
    mock_questionary.confirm.return_value.ask.side_effect = [
        True,  # Use default agent
        True,  # Add custom agents
        True,  # Add another agent
        False,  # No more agents
        True,  # Use database
        True,  # Use auth
        True,  # Use tracing
        True,  # Use feedback loop
        True,  # Use validation node
    ]
    mock_questionary.select.return_value.ask.side_effect = [
        "analysis",  # default intent
        "mysql",  # database backend
    ]
    mock_questionary.checkbox.return_value.ask.return_value = [
        "conversations",
        "messages",
    ]  # database tables
    
    # Run the wizard
    wizard = ProjectWizard()
    config = wizard.run()
    
    # Verify the result
    assert isinstance(config, ProjectConfig)
    assert config.metadata.name == "full-project"
    assert config.metadata.description == "A full test project"
    assert config.metadata.version == "1.0.0"
    assert len(config.agents) >= 3  # Default + 2 custom agents
    assert config.database.backend.value == "mysql"
    assert "conversations" in config.database.tables
    assert "messages" in config.database.tables
    assert config.security.enable_auth is True
    assert config.observability.enable_tracing is True
    assert config.workflow.enable_feedback_loop is True
    assert config.workflow.enable_validation_node is True