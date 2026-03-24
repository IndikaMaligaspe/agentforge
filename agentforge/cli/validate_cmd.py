"""
agentforge validate

Validates project.yaml schema without generating any files.
"""
import typer
from pathlib import Path
from rich.console import Console
from pydantic import ValidationError
from ..schema.loader import load

validate_app = typer.Typer()
console = Console()

@validate_app.callback(invoke_without_command=True)
def validate(
    config: Path = typer.Option(Path("project.yaml"), "--config", "-c"),
):
    """Validate project.yaml schema. Exits 0 on success, 1 on error."""
    try:
        cfg = load(config)
        console.print(f"[green]✓[/green] project.yaml is valid")
        console.print(f"  Project: [bold]{cfg.metadata.name}[/bold]")
        console.print(f"  Agents: {', '.join(a.key for a in cfg.agents)}")
    except ValidationError as exc:
        console.print(f"[red]✗[/red] Validation errors in {config}:")
        for err in exc.errors():
            loc = " → ".join(str(x) for x in err["loc"])
            console.print(f"  [red]•[/red] {loc}: {err['msg']}")
        raise typer.Exit(1)
    except FileNotFoundError:
        console.print(f"[red]✗[/red] File not found: {config}")
        raise typer.Exit(1)