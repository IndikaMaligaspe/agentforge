"""
agentforge add agent|node|middleware

Appends a single component to an existing project.

Flag-driven mode
-----------------
When ``--agents`` or tool flags (``--mcp``, ``--http``, ``--agent``) are
supplied the interactive prompt is skipped and agents/tools are created
directly from the flag values.

Entry and pattern flags are intentionally absent from this command — those
only apply at project initialisation time (``agentforge init``).
"""
import typer
from pathlib import Path
from typing import Optional
from rich.console import Console
from ..schema.loader import load, dump
from ..schema.models import AgentConfig, LLMModel
from ..prompts.questions import ask_agent_config
from ..engine.renderer import TemplateRenderer
from ..writer.scaffold import ScaffoldWriter
from .flags import flags_to_config_patch, parse_agents, build_tool_entry

add_app = typer.Typer()
console = Console()


@add_app.command("agent")
def add_agent(
    config: Path = typer.Option(Path("project.yaml"), "--config", "-c"),
    output: Path = typer.Option(None, "--output", "-o"),
    # ── Flag-driven agent addition ────────────────────────────────────────────
    agents_csv: Optional[str] = typer.Option(
        None, "--agents",
        help="Comma-separated agent keys to add, e.g. 'alpha,beta'. "
             "Class names are derived automatically (AlphaAgent, BetaAgent). "
             "Skips the interactive prompt.",
    ),
    mcp_tools: Optional[list[str]] = typer.Option(
        None, "--mcp",
        help="MCP tool name to attach to all new agents. May be specified multiple times.",
    ),
    http_tools: Optional[list[str]] = typer.Option(
        None, "--http",
        help="HTTP tool name to attach to all new agents (placeholder URL generated). "
             "May be specified multiple times.",
    ),
    agent_tools: Optional[list[str]] = typer.Option(
        None, "--agent",
        help="Agent-call tool name to attach to all new agents (placeholder service URL generated). "
             "May be specified multiple times.",
    ),
):
    """Interactively add a new agent to an existing project.

    When ``--agents`` is supplied the interactive prompt is skipped and the
    listed agents are appended directly.  Tool flags (``--mcp``, ``--http``,
    ``--agent``) attach tools to every agent created by ``--agents``.
    """
    project_config = load(config)

    if agents_csv:
        # Non-interactive path: build agents from flags.
        raw_agents = parse_agents(agents_csv)

        # Build tool entries to attach to each new agent.
        tool_entries: list[dict] = []
        for name in (mcp_tools or []):
            tool_entries.append(build_tool_entry("mcp", name))
        for name in (http_tools or []):
            tool_entries.append(build_tool_entry("http", name))
        for name in (agent_tools or []):
            tool_entries.append(build_tool_entry("agent", name))

        existing_keys = {a.key for a in project_config.agents}
        new_agents: list[AgentConfig] = []

        for raw in raw_agents:
            key = raw["key"]
            if key in existing_keys:
                console.print(f"[yellow]Agent '{key}' already exists — skipping.[/yellow]")
                continue
            agent_cfg = AgentConfig(
                key=key,
                class_name=raw["class_name"],
                llm_model=LLMModel.GPT4O_MINI,
                tools=tool_entries,
            )
            project_config.agents.append(agent_cfg)
            new_agents.append(agent_cfg)
            existing_keys.add(key)

        if not new_agents:
            console.print("[yellow]No new agents to add.[/yellow]")
            return

        dump(project_config, config)

        out_dir = output or Path(project_config.metadata.name)
        renderer = TemplateRenderer()
        writer = ScaffoldWriter(out_dir, overwrite=True)

        for agent_cfg in new_agents:
            rendered = renderer.render_agent(agent_cfg, project_config)
            for rel_path, content in rendered:
                writer.write(rel_path, content)
                console.print(f"[green]✓[/green] {out_dir / rel_path}")
            console.print(f"[green]✓[/green] Agent '{agent_cfg.key}' added and project.yaml updated.")

    else:
        # Interactive path (original behaviour, unchanged).
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
