"""
Thin wrapper around the `gh` CLI for GitHub repo management.
Requires:  brew install gh  AND  gh auth login
"""
import subprocess
import shutil
import sys
from pathlib import Path
from typing import Tuple, Optional
from rich.console import Console

console = Console()

class GitHubCLIError(Exception):
    """Exception raised for GitHub CLI errors."""
    pass

def validate_gh_installation() -> Tuple[bool, Optional[str]]:
    """
    Validate that GitHub CLI is installed and available.
    
    Returns:
        Tuple of (is_valid, error_message)
        - is_valid: True if GitHub CLI is installed, False otherwise
        - error_message: Error message if not valid, None otherwise
    """
    if not shutil.which("gh"):
        return False, "GitHub CLI (gh) not found. Install: https://cli.github.com"
    return True, None

def validate_gh_authentication() -> Tuple[bool, Optional[str]]:
    """
    Validate that GitHub CLI is authenticated.
    
    Returns:
        Tuple of (is_valid, error_message)
        - is_valid: True if GitHub CLI is authenticated, False otherwise
        - error_message: Error message if not valid, None otherwise
    """
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            check=False,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            return False, "GitHub CLI not authenticated. Run: gh auth login"
        return True, None
    except Exception as e:
        return False, f"Error checking GitHub authentication: {str(e)}"

def _require_gh() -> None:
    """
    Check if GitHub CLI is installed and authenticated.
    Exits the program if requirements are not met.
    """
    # Check installation
    is_installed, install_error = validate_gh_installation()
    if not is_installed:
        console.print(f"[red]✗[/red] {install_error}")
        sys.exit(1)
    
    # Check authentication
    is_authenticated, auth_error = validate_gh_authentication()
    if not is_authenticated:
        console.print(f"[red]✗[/red] {auth_error}")
        sys.exit(1)

def create_repo(name: str, description: str, private: bool, path: Path) -> None:
    """
    Create a new GitHub repository and push the local project to it.
    
    Args:
        name: Repository name
        description: Repository description
        private: Whether the repository should be private
        path: Path to the local project directory
        
    Raises:
        GitHubCLIError: If repository creation fails
    """
    _require_gh()
    
    cmd = [
        "gh", "repo", "create", name,
        "--description", description,
        "--source", str(path),
        "--push",
        "--private" if private else "--public",
    ]
    
    try:
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            error_msg = result.stderr.strip() or "Unknown error"
            console.print(f"[red]✗[/red] Failed to create GitHub repository: {error_msg}")
            raise GitHubCLIError(f"Failed to create GitHub repository: {error_msg}")
        console.print(f"[green]✓[/green] GitHub repo created: github.com/<owner>/{name}")
    except subprocess.SubprocessError as e:
        console.print(f"[red]✗[/red] Error executing GitHub CLI: {str(e)}")
        raise GitHubCLIError(f"Error executing GitHub CLI: {str(e)}")

def sync(path: Path, message: str = "chore: agentforge scaffold") -> None:
    """
    Sync local changes to GitHub repository.
    
    Args:
        path: Path to the local project directory
        message: Commit message
        
    Raises:
        GitHubCLIError: If syncing fails
    """
    _require_gh()
    
    commands = [
        ["git", "-C", str(path), "add", "."],
        ["git", "-C", str(path), "commit", "-m", message],
        ["git", "-C", str(path), "push"],
    ]
    
    for cmd in commands:
        try:
            result = subprocess.run(cmd, check=False, capture_output=True, text=True)
            if result.returncode != 0:
                cmd_name = cmd[0] + " " + cmd[1] if len(cmd) > 1 else cmd[0]
                error_msg = result.stderr.strip() or "Unknown error"
                console.print(f"[red]✗[/red] Failed to execute {cmd_name}: {error_msg}")
                raise GitHubCLIError(f"Failed to execute {cmd_name}: {error_msg}")
        except subprocess.SubprocessError as e:
            console.print(f"[red]✗[/red] Error executing git command: {str(e)}")
            raise GitHubCLIError(f"Error executing git command: {str(e)}")
    
    console.print(f"[green]✓[/green] Changes pushed to GitHub")