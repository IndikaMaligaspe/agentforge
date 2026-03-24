"""
agentforge init - Interactive Project Configuration Wizard

This module implements the 'agentforge init' command, which runs an interactive
wizard to guide users through creating a project.yaml configuration file.
The wizard collects information about the project, agents, database, workflow,
API, observability, and security settings.

The generated project.yaml file serves as the single source of truth for
the project configuration and can be used with 'agentforge new' to scaffold
a complete project.
"""
import typer
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from ..prompts.wizard import run_wizard
from ..schema.loader import dump

init_app = typer.Typer()
console = Console()

@init_app.callback(invoke_without_command=True)
def init(
    output: Path = typer.Option(Path("."), "--output", "-o", help="Directory to write project.yaml"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing project.yaml"),
):
    """
    Launch the interactive wizard to generate project.yaml.
    
    This function runs a step-by-step interactive wizard that guides the user
    through creating a project.yaml configuration file. The wizard collects
    information about the project, agents, database, workflow, API settings,
    observability, and security options.
    
    Args:
        output: Directory where project.yaml will be written (default: current directory)
        force: Whether to overwrite an existing project.yaml file (default: False)
        
    Raises:
        typer.Exit: If project.yaml already exists and --force is not specified
        
    Example:
        agentforge init
        agentforge init --output ./my-project
        agentforge init --force
    """
    target = output / "project.yaml"
    if target.exists() and not force:
        console.print(f"[yellow]project.yaml already exists at {target}. Use --force to overwrite.[/yellow]")
        raise typer.Exit(1)

    console.print(Panel("[bold green]agentforge init[/bold green] — Agentic Project Wizard", expand=False))

    config = run_wizard()              # returns ProjectConfig
    output.mkdir(parents=True, exist_ok=True)
    dump(config, target)

    console.print(f"[green]✓[/green] project.yaml written to [bold]{target}[/bold]")
    console.print("Run [bold]agentforge new[/bold] to scaffold your project.")