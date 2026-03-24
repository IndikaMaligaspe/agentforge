"""
Thin wrapper around the `gh` CLI for GitHub repo management.
Requires:  brew install gh  AND  gh auth login
"""
import subprocess
import shutil
import sys
from pathlib import Path
from rich.console import Console

console = Console()

def _require_gh() -> None:
    if not shutil.which("gh"):
        console.print("[red]✗[/red] GitHub CLI (gh) not found. Install: https://cli.github.com")
        sys.exit(1)

def create_repo(name: str, description: str, private: bool, path: Path) -> None:
    _require_gh()
    cmd = [
        "gh", "repo", "create", name,
        "--description", description,
        "--source", str(path),
        "--push",
        "--private" if private else "--public",
    ]
    subprocess.run(cmd, check=True)
    console.print(f"[green]✓[/green] GitHub repo created: github.com/<owner>/{name}")

def sync(path: Path, message: str = "chore: agentforge scaffold") -> None:
    _require_gh()
    for cmd in [
        ["git", "-C", str(path), "add", "."],
        ["git", "-C", str(path), "commit", "-m", message],
        ["git", "-C", str(path), "push"],
    ]:
        subprocess.run(cmd, check=True)
    console.print(f"[green]✓[/green] Changes pushed to GitHub")