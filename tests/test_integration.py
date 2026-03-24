"""
Integration tests for agentforge CLI tool.

These tests verify the end-to-end functionality of the CLI tool
by simulating actual usage scenarios.
"""
import os
import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

from agentforge.cli.app import app
from agentforge.schema.models import ProjectConfig
from agentforge.schema.loader import load_project_config
from typer.testing import CliRunner

@pytest.fixture
def runner():
    """Create a CLI runner for testing."""
    return CliRunner()

@pytest.fixture
def temp_project_dir():
    """Create a temporary directory for project generation."""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir)

@pytest.fixture
def mock_renderer():
    """Mock the template renderer to avoid actual file generation."""
    with patch("agentforge.writer.scaffold.TemplateRenderer") as mock:
        renderer_instance = MagicMock()
        mock.return_value = renderer_instance
        # Mock render_all to return some fake files
        renderer_instance.render_all.return_value = [
            (Path("backend/main.py"), "# Main file content"),
            (Path("backend/agents/base_agent.py"), "# Base agent content"),
            (Path("README.md"), "# Project README"),
        ]
        yield mock

@pytest.fixture
def mock_wizard():
    """Mock the project wizard to return a predefined config."""
    with patch("agentforge.cli.init_cmd.ProjectWizard") as mock:
        wizard_instance = MagicMock()
        mock.return_value = wizard_instance
        
        # Create a minimal project config
        config = ProjectConfig(
            metadata={
                "name": "test-project",
                "description": "Test project for integration tests",
                "version": "0.1.0",
            },
            agents=[{
                "key": "analysis",
                "name": "Analysis Agent",
                "description": "Analyzes data",
            }],
            workflow={
                "default_intent": "analysis",
            }
        )
        
        wizard_instance.run.return_value = config
        yield mock

def test_init_command(runner, temp_project_dir, mock_renderer, mock_wizard):
    """Test the 'init' command for project initialization."""
    with patch("agentforge.cli.init_cmd.Path.cwd", return_value=temp_project_dir):
        # Run the init command
        result = runner.invoke(app, ["init"])
        
        # Check the command executed successfully
        assert result.exit_code == 0
        
        # Verify the wizard was called
        mock_wizard.return_value.run.assert_called_once()
        
        # Verify the renderer was called
        mock_renderer.return_value.render_all.assert_called_once()

def test_new_agent_command(runner, temp_project_dir, mock_renderer):
    """Test the 'new agent' command for adding a new agent."""
    # Create a minimal project.yaml file
    project_dir = temp_project_dir
    os.makedirs(project_dir / "backend" / "agents", exist_ok=True)
    
    with open(project_dir / "project.yaml", "w") as f:
        f.write("""
metadata:
  name: test-project
  description: Test project
  version: 0.1.0
agents:
  - key: analysis
    name: Analysis Agent
    description: Analyzes data
workflow:
  default_intent: analysis
        """)
    
    # Mock the renderer to return agent files
    renderer_instance = mock_renderer.return_value
    renderer_instance.render_agent.return_value = [
        (Path("backend/agents/sql_agent.py"), "# SQL agent content"),
        (Path("backend/agents/registry.py"), "# Updated registry content"),
    ]
    
    # Mock cwd to return our temp directory
    with patch("agentforge.cli.new_cmd.Path.cwd", return_value=project_dir):
        # Run the new agent command
        result = runner.invoke(app, [
            "new", "agent",
            "--key", "sql",
            "--name", "SQL Agent",
            "--description", "Executes SQL queries"
        ])
        
        # Check the command executed successfully
        assert result.exit_code == 0
        
        # Verify the renderer was called with correct parameters
        renderer_instance.render_agent.assert_called_once()
        
        # Get the arguments passed to render_agent
        args, kwargs = renderer_instance.render_agent.call_args
        
        # Verify the agent config
        agent_config = args[0]
        assert agent_config.key == "sql"
        assert agent_config.name == "SQL Agent"
        assert agent_config.description == "Executes SQL queries"

def test_validate_command(runner, temp_project_dir):
    """Test the 'validate' command for project validation."""
    # Create a minimal project.yaml file
    project_dir = temp_project_dir
    
    with open(project_dir / "project.yaml", "w") as f:
        f.write("""
metadata:
  name: test-project
  description: Test project
  version: 0.1.0
agents:
  - key: analysis
    name: Analysis Agent
    description: Analyzes data
workflow:
  default_intent: analysis
        """)
    
    # Mock cwd to return our temp directory
    with patch("agentforge.cli.validate_cmd.Path.cwd", return_value=project_dir):
        # Run the validate command
        result = runner.invoke(app, ["validate"])
        
        # Check the command executed successfully
        assert result.exit_code == 0
        
        # Verify the output indicates successful validation
        assert "valid" in result.stdout.lower()