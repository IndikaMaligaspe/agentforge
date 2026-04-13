"""
agentforge new - Project Scaffolding Command

This module implements the 'agentforge new' command, which scaffolds a complete
project based on a project.yaml configuration file. It renders all Jinja2 templates
and writes them to the file system, creating the full directory structure.

The command supports dry-run mode to preview files without writing them, and
can be configured to overwrite existing files if needed.
"""
import typer
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from ..schema.loader import load
from ..engine.renderer import TemplateRenderer
from ..writer.scaffold import ScaffoldWriter
from ..utils.git import init_repo

new_app = typer.Typer()
console = Console()

@new_app.callback(invoke_without_command=True)
def new(
    config: Path = typer.Option(Path("project.yaml"), "--config", "-c", help="Path to project.yaml"),
    output: Path = typer.Option(None, "--output", "-o", help="Output directory (default: ./<project_name>)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print planned files without writing"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing files"),
    git_init: bool = typer.Option(False, "--git-init/--no-git-init", help="Run 'git init' in the generated project after scaffolding."),
):
    """
    Scaffold a full agentic project from project.yaml.

    This function reads a project.yaml configuration file, validates it against
    the schema, renders all templates, and writes the files to create a complete
    project structure. It creates the directory structure, agent files, workflow
    graph, API endpoints, and all other components defined in the configuration.

    Args:
        config: Path to the project.yaml file (default: ./project.yaml)
        output: Output directory (default: ./<project_name> from config)
        dry_run: If True, only print files that would be written without writing them
        overwrite: If True, overwrite existing files (default: False)
        git_init: If True, run ``git init`` in the generated project directory

    Raises:
        ValidationError: If the project.yaml file doesn't match the schema
        FileNotFoundError: If the project.yaml file doesn't exist

    Example:
        agentforge new
        agentforge new --config ./project.yaml --output ./my-api --dry-run
        agentforge new --overwrite
        agentforge new --git-init
    """
    project_config = load(config)          # validates schema
    out_dir = output or Path(project_config.metadata.name)

    renderer = TemplateRenderer()
    writer = ScaffoldWriter(out_dir, overwrite=overwrite)

    # Render all templates → list of (relative_path, rendered_content)
    rendered_files = renderer.render_all(project_config)

    if dry_run:
        console.print("[bold]Dry-run — files that would be written:[/bold]")
        for rel_path, _ in rendered_files:
            console.print(f"  [cyan]{out_dir / rel_path}[/cyan]")
        return

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as progress:
        task = progress.add_task("Scaffolding project...", total=len(rendered_files))
        for rel_path, content in rendered_files:
            writer.write(rel_path, content)
            progress.advance(task)

    console.print(f"[green]✓[/green] Project scaffolded at [bold]{out_dir}[/bold]")
    console.print(f"  [dim]{len(rendered_files)} files written[/dim]")

    if git_init:
        if not init_repo(out_dir):
            err_console = Console(stderr=True)
            err_console.print(
                "[yellow]Warning:[/yellow] git init failed or git is not available. "
                "Scaffolding succeeded — initialise the repository manually if needed."
            )
