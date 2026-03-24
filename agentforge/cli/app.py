"""
Root Typer application for agentforge CLI.
"""
import typer
from rich.console import Console
from .init_cmd import init_app
from .new_cmd import new_app
from .add_cmd import add_app
from .validate_cmd import validate_app
from .gh_cmd import gh_app

console = Console()

app = typer.Typer(
    name="agentforge",
    help="Scaffold production-grade agentic Python projects.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)

# Mount sub-applications
app.add_typer(init_app,     name="init",     help="Interactive wizard — create project.yaml")
app.add_typer(new_app,      name="new",      help="Scaffold project from project.yaml")
app.add_typer(add_app,      name="add",      help="Add agent / node / middleware to existing project")
app.add_typer(validate_app, name="validate", help="Validate project.yaml without scaffolding")
app.add_typer(gh_app,       name="gh",       help="GitHub integration (requires gh CLI)")

if __name__ == "__main__":
    app()