"""
agentforge add agent|node|middleware

Appends a single component to an existing project.
"""
import typer
from pathlib import Path
from rich.console import Console
from ..schema.loader import load, dump
from ..prompts.questions import ask_agent_config
from ..engine.renderer import TemplateRenderer
from ..writer.scaffold import ScaffoldWriter

add_app = typer.Typer()
console = Console()

@add_app.command("agent")
def add_agent(
    config: Path = typer.Option(Path("project.yaml"), "--config", "-c"),
    output: Path = typer.Option(None, "--output", "-o"),
):
    """Interactively add a new agent to an existing project."""
    project_config = load(config)
    agent_cfg = ask_agent_config(existing_keys={a.key for a in project_config.agents})
    project_config.agents.append(agent_cfg)
    dump(project_config, config)

    out_dir = output or Path(project_config.metadata.name)
    renderer = TemplateRenderer()
    writer = ScaffoldWriter(out_dir, overwrite=True)

    rendered = renderer.render_agent(agent_cfg, project_config)
    for rel_path, content in rendered:
        writer.write(rel_path, content)
        console.print(f"[green]✓[/green] {out_dir / rel_path}")

    console.print(f"[green]✓[/green] Agent '{agent_cfg.key}' added and project.yaml updated.")

@add_app.command("node")
def add_node(
    config: Path = typer.Option(Path("project.yaml"), "--config", "-c"),
    output: Path = typer.Option(None, "--output", "-o"),
):
    """Add a custom graph node (not implemented yet)."""
    console.print("[yellow]Not implemented yet.[/yellow]")
    raise typer.Exit(1)

@add_app.command("middleware")
def add_middleware(
    config: Path = typer.Option(Path("project.yaml"), "--config", "-c"),
    output: Path = typer.Option(None, "--output", "-o"),
):
    """Add a custom middleware (not implemented yet)."""
    console.print("[yellow]Not implemented yet.[/yellow]")
    raise typer.Exit(1)