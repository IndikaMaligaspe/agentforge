"""
Tests for GitHub CLI integration.
"""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import subprocess

from agentforge.github.gh import (
    validate_gh_installation,
    validate_gh_authentication,
    create_repo,
    sync,
    GitHubCLIError
)

@pytest.fixture
def mock_subprocess():
    """Mock subprocess to avoid actual command execution."""
    with patch("agentforge.github.gh.subprocess") as mock:
        yield mock

@pytest.fixture
def mock_shutil():
    """Mock shutil to control which command is available."""
    with patch("agentforge.github.gh.shutil") as mock:
        yield mock

def test_validate_gh_installation_success(mock_shutil):
    """Test successful GitHub CLI installation validation."""
    mock_shutil.which.return_value = "/usr/local/bin/gh"
    is_valid, error = validate_gh_installation()
    assert is_valid is True
    assert error is None
    mock_shutil.which.assert_called_once_with("gh")

def test_validate_gh_installation_failure(mock_shutil):
    """Test failed GitHub CLI installation validation."""
    mock_shutil.which.return_value = None
    is_valid, error = validate_gh_installation()
    assert is_valid is False
    assert "GitHub CLI (gh) not found" in error
    mock_shutil.which.assert_called_once_with("gh")

def test_validate_gh_authentication_success(mock_subprocess):
    """Test successful GitHub CLI authentication validation."""
    process_mock = MagicMock()
    process_mock.returncode = 0
    process_mock.stdout = "Logged in to github.com as username"
    mock_subprocess.run.return_value = process_mock
    
    is_valid, error = validate_gh_authentication()
    assert is_valid is True
    assert error is None
    mock_subprocess.run.assert_called_once()

def test_validate_gh_authentication_failure(mock_subprocess):
    """Test failed GitHub CLI authentication validation."""
    process_mock = MagicMock()
    process_mock.returncode = 1
    process_mock.stderr = "You are not logged in to GitHub"
    mock_subprocess.run.return_value = process_mock
    
    is_valid, error = validate_gh_authentication()
    assert is_valid is False
    assert "GitHub CLI not authenticated" in error
    mock_subprocess.run.assert_called_once()

def test_create_repo_success(mock_subprocess, mock_shutil):
    """Test successful repository creation."""
    # Mock successful installation and authentication checks
    mock_shutil.which.return_value = "/usr/local/bin/gh"
    
    auth_process = MagicMock()
    auth_process.returncode = 0
    
    create_process = MagicMock()
    create_process.returncode = 0
    
    mock_subprocess.run.side_effect = [auth_process, create_process]
    
    # Call the function
    create_repo("test-repo", "Test repository", True, Path("/path/to/project"))
    
    # Verify the correct command was executed
    calls = mock_subprocess.run.call_args_list
    assert len(calls) == 2  # auth check + create repo
    
    # Check the create repo command
    create_call = calls[1]
    cmd_args = create_call[0][0]
    assert "gh" in cmd_args
    assert "repo" in cmd_args
    assert "create" in cmd_args
    assert "test-repo" in cmd_args
    assert "--private" in cmd_args

def test_create_repo_failure(mock_subprocess, mock_shutil):
    """Test repository creation failure."""
    # Mock successful installation and authentication checks
    mock_shutil.which.return_value = "/usr/local/bin/gh"
    
    auth_process = MagicMock()
    auth_process.returncode = 0
    
    create_process = MagicMock()
    create_process.returncode = 1
    create_process.stderr = "Repository already exists"
    
    mock_subprocess.run.side_effect = [auth_process, create_process]
    
    # Call the function and expect an exception
    with pytest.raises(GitHubCLIError) as excinfo:
        create_repo("test-repo", "Test repository", True, Path("/path/to/project"))
    
    assert "Failed to create GitHub repository" in str(excinfo.value)

def test_sync_success(mock_subprocess, mock_shutil):
    """Test successful repository sync."""
    # Mock successful installation and authentication checks
    mock_shutil.which.return_value = "/usr/local/bin/gh"
    
    auth_process = MagicMock()
    auth_process.returncode = 0
    
    add_process = MagicMock()
    add_process.returncode = 0
    
    commit_process = MagicMock()
    commit_process.returncode = 0
    
    push_process = MagicMock()
    push_process.returncode = 0
    
    mock_subprocess.run.side_effect = [auth_process, add_process, commit_process, push_process]
    
    # Call the function
    sync(Path("/path/to/project"), "test commit message")
    
    # Verify the correct commands were executed
    calls = mock_subprocess.run.call_args_list
    assert len(calls) == 4  # auth check + 3 git commands
    
    # Check the git commands
    assert "add" in calls[1][0][0]
    assert "commit" in calls[2][0][0]
    assert "push" in calls[3][0][0]

def test_sync_failure(mock_subprocess, mock_shutil):
    """Test repository sync failure."""
    # Mock successful installation and authentication checks
    mock_shutil.which.return_value = "/usr/local/bin/gh"
    
    auth_process = MagicMock()
    auth_process.returncode = 0
    
    add_process = MagicMock()
    add_process.returncode = 0
    
    commit_process = MagicMock()
    commit_process.returncode = 1
    commit_process.stderr = "Nothing to commit"
    
    mock_subprocess.run.side_effect = [auth_process, add_process, commit_process]
    
    # Call the function and expect an exception
    with pytest.raises(GitHubCLIError) as excinfo:
        sync(Path("/path/to/project"), "test commit message")
    
    assert "Failed to execute git commit" in str(excinfo.value)