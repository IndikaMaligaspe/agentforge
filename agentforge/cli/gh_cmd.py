"""
agentforge gh

GitHub integration commands.
"""
import typer
from pathlib import Path
from rich.console import Console
from ..github.gh import create_repo, sync
from ..schema.loader import load

gh_app = typer.Typer()
console = Console()

@gh_app.command("create")
def gh_create(
    config: Path = typer.Option(Path("project.yaml"), "--config", "-c"),
    output: Path = typer.Option(None, "--output", "-o"),
    private: bool = typer.Option(False, "--private", help="Create a private repository"),
):
    """Create a GitHub repo from the scaffolded project and push."""
    cfg = load(config)
    out = output or Path(cfg.metadata.name)
    create_repo(cfg.metadata.name, cfg.metadata.description, private, out)

@gh_app.command("sync")
def gh_sync(
    path: Path = typer.Option(Path("."), "--path", "-p"),
    message: str = typer.Option("chore: agentforge update", "--message", "-m"),
):
    """Push local changes to GitHub."""
    sync(path, message)