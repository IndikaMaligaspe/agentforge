"""
agentforge init - Interactive Project Configuration Wizard

This module implements the 'agentforge init' command, which runs an interactive
wizard to guide users through creating a project.yaml configuration file.
The wizard collects information about the project, agents, database, workflow,
API, observability, and security settings.

The generated project.yaml file serves as the single source of truth for
the project configuration and can be used with 'agentforge new' to scaffold
a complete project.

Non-interactive (flag-driven) mode
------------------------------------
When any v2 schema flag is supplied (``--withPlanner``, ``--agents``, etc.)
the wizard is **skipped** and the config is produced directly from the flags
combined with schema defaults.  ``--name`` provides the project name in this
mode (defaults to ``"my_agent_project"``).

Mutual exclusion
-----------------
- Entry group: ``--withIntentRouter``, ``--withPassthrough``, ``--withDirectInput``
  (at most one may be given).
- Pattern group: ``--withReactAgent``, ``--withWorkflow``, ``--withFanout``,
  ``--withOrchestrator``, ``--withPlanner`` (at most one may be given).

Mutual exclusion is enforced at the CLI layer before the translator is called.
"""
import typer
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from ..prompts.wizard import run_wizard
from ..schema.loader import dump
from ..schema.models import ProjectConfig, AgentConfig, LLMModel, pattern_supports_feedback_loop
from .flags import (
    flags_to_config_patch,
    ORCHESTRATOR_KIND_CHOICES,
)

_DEFAULT_PROJECT_NAME = "my_agent_project"

init_app = typer.Typer()
console = Console()


# ── Mutual-exclusion helpers ──────────────────────────────────────────────────

def _check_entry_mutual_exclusion(
    with_intent_router: bool,
    with_passthrough: bool,
    with_direct_input: bool,
) -> Optional[str]:
    """Return the selected entry type, or raise a Typer error if more than one is set."""
    selected = [
        ("intent_router", with_intent_router),
        ("passthrough", with_passthrough),
        ("direct", with_direct_input),
    ]
    active = [(name, flag) for name, flag in selected if flag]
    if len(active) > 1:
        names = ", ".join(f"--with{n.replace('_', '').title()}" for n, _ in active)
        raise typer.BadParameter(
            f"Entry flags are mutually exclusive — only one may be supplied. "
            f"Got: {names}",
            param_hint="--withIntentRouter / --withPassthrough / --withDirectInput",
        )
    return active[0][0] if active else None


def _check_pattern_mutual_exclusion(
    with_react: bool,
    with_workflow: bool,
    with_fanout: bool,
    with_orchestrator: bool,
    with_planner: bool,
) -> Optional[str]:
    """Return the selected pattern, or raise a Typer error if more than one is set."""
    selected = [
        ("react", with_react),
        ("workflow", with_workflow),
        ("fanout", with_fanout),
        ("orchestrator", with_orchestrator),
        ("planner", with_planner),
    ]
    active = [(name, flag) for name, flag in selected if flag]
    if len(active) > 1:
        names = ", ".join(f"--with{n.capitalize()}" for n, _ in active)
        raise typer.BadParameter(
            f"Pattern flags are mutually exclusive — only one may be supplied. "
            f"Got: {names}",
            param_hint="--withReactAgent / --withWorkflow / --withFanout / --withOrchestrator / --withPlanner",
        )
    return active[0][0] if active else None


def _any_v2_flag_given(
    entry_type: Optional[str],
    pattern: Optional[str],
    orchestrator_kind: Optional[str],
    agents_csv: Optional[str],
    mcp_tools: Optional[list],
    http_tools: Optional[list],
    agent_tools: Optional[list],
) -> bool:
    """Return True when at least one v2 flag was explicitly supplied."""
    return any([
        entry_type is not None,
        pattern is not None,
        orchestrator_kind is not None,
        agents_csv is not None,
        mcp_tools,
        http_tools,
        agent_tools,
    ])


def _build_config_from_flags(
    name: str,
    patch: dict,
) -> ProjectConfig:
    """Construct a minimal valid ProjectConfig from a flags patch dict.

    Uses schema defaults for all fields not present in *patch*.  A minimal
    ``metadata`` block and at least one agent are required by the schema;
    this function provides sensible defaults if the patch does not supply them.

    Special handling:

    - ``workflow.default_intent`` is set to the first agent key so the
      ``check_default_intent_registered`` validator passes.
    - ``workflow.enable_feedback_loop`` and ``workflow.enable_validation_node``
      are set to ``False`` for patterns that do not support them (everything
      except ``orchestrator`` and ``react``), so
      ``check_workflow_flags_pattern_compat`` does not reject the config.
    - ``pattern='workflow'`` requires at least one ``workflow_sm.steps`` entry;
      a minimal placeholder step ``{"key": "step_one", "description": ""}`` is
      injected automatically.

    Args:
        name: Project slug name (``metadata.name``).
        patch: Patch dict produced by ``flags_to_config_patch``.

    Returns:
        A validated ``ProjectConfig`` instance.
    """
    pattern = patch.get("pattern")

    # Build agent list — must have at least one agent.
    raw_agents = patch.get("agents")
    if raw_agents:
        agent_dicts = [
            {
                "key": a["key"],
                "class_name": a["class_name"],
                "llm_model": LLMModel.GPT4O_MINI.value,
                "tools": a.get("tools", []),
            }
            for a in raw_agents
        ]
    else:
        # Default: a single placeholder agent derived from the project name.
        default_key = name.split("_")[0] if "_" in name else name
        # Guard against reserved agent keys.
        reserved = {"base", "registry", "supervisor", "router", "answer"}
        if default_key in reserved:
            default_key = f"{default_key}_main"
        default_class = "".join(p.capitalize() for p in default_key.split("_")) + "Agent"
        agent_dicts = [
            {
                "key": default_key,
                "class_name": default_class,
                "llm_model": LLMModel.GPT4O_MINI.value,
                "tools": [],
            }
        ]

    first_agent_key = agent_dicts[0]["key"]

    # Workflow defaults — adjust for pattern compatibility.
    # Patterns that do not support enable_feedback_loop or enable_validation_node
    # (workflow, fanout, planner) are excluded by pattern_supports_feedback_loop.
    pattern_is_compatible = pattern_supports_feedback_loop(pattern)
    workflow_dict: dict = {
        "default_intent": first_agent_key,
        "enable_feedback_loop": pattern_is_compatible,
        "enable_validation_node": pattern_is_compatible,
    }

    # Assemble the raw dict understood by ProjectConfig.model_validate.
    raw: dict = {
        "metadata": {
            "name": name,
            "description": "An agentic project scaffolded by agentforge",
            "python_version": "3.11",
            "author": "Your Name",
            "email": "you@example.com",
        },
        "agents": agent_dicts,
        "workflow": workflow_dict,
    }

    # Merge v2 fields from patch.
    for key in ("entry", "pattern", "orchestrator"):
        if key in patch:
            raw[key] = patch[key]

    # pattern='workflow' requires at least one step in workflow_sm.
    if pattern == "workflow" and "workflow_sm" not in raw:
        raw["workflow_sm"] = {
            "steps": [{"key": "step_one", "description": "First workflow step"}]
        }
        console.print("[yellow]Injected placeholder workflow_sm.steps — edit project.yaml before use.[/yellow]")

    return ProjectConfig.model_validate(raw)


# ── Command ───────────────────────────────────────────────────────────────────

@init_app.callback(invoke_without_command=True)
def init(
    output: Path = typer.Option(Path("."), "--output", "-o", help="Directory to write project.yaml"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing project.yaml"),
    # Non-interactive project name (used when any v2 flag is supplied)
    name: Optional[str] = typer.Option(
        None, "--name", "-n",
        help=f"Project slug name for non-interactive flag-driven mode (defaults to {_DEFAULT_PROJECT_NAME!r}).",
    ),
    # ── Entry group (mutually exclusive) ──────────────────────────────────────
    with_intent_router: bool = typer.Option(
        False, "--withIntentRouter",
        help="Entry type: LLM parses free text and routes to an agent by intent (entry.type=intent_router).",
    ),
    with_passthrough: bool = typer.Option(
        False, "--withPassthrough",
        help="Entry type: caller supplies the intent; LLM only extracts structured inputs (entry.type=passthrough).",
    ),
    with_direct_input: bool = typer.Option(
        False, "--withDirectInput",
        help="Entry type: structured params arrive directly — no LLM parsing at entry (entry.type=direct).",
    ),
    # ── Pattern group (mutually exclusive) ────────────────────────────────────
    with_react_agent: bool = typer.Option(
        False, "--withReactAgent",
        help="Execution pattern: single ReAct tool-calling agent loop (pattern=react).",
    ),
    with_workflow: bool = typer.Option(
        False, "--withWorkflow",
        help="Execution pattern: deterministic state-machine workflow (pattern=workflow).",
    ),
    with_fanout: bool = typer.Option(
        False, "--withFanout",
        help="Execution pattern: parallel fan-out to multiple agents (pattern=fanout).",
    ),
    with_orchestrator: bool = typer.Option(
        False, "--withOrchestrator",
        help="Execution pattern: LLM or rule-based orchestrator dispatches work to agents (pattern=orchestrator).",
    ),
    with_planner: bool = typer.Option(
        False, "--withPlanner",
        help="Execution pattern: plan-and-execute loop with optional replanning (pattern=planner).",
    ),
    # ── Orchestrator kind ─────────────────────────────────────────────────────
    orchestrator_kind: Optional[str] = typer.Option(
        None, "--orchestratorKind",
        help="Orchestrator sub-kind: 'llm' (dynamic LLM routing) or 'rule' (deterministic). "
             "Only meaningful with --withOrchestrator.",
    ),
    # ── Agents ────────────────────────────────────────────────────────────────
    agents_csv: Optional[str] = typer.Option(
        None, "--agents",
        help="Comma-separated agent keys to scaffold, e.g. 'alpha,beta'. "
             "Class names are derived automatically (AlphaAgent, BetaAgent).",
    ),
    # ── Tools (may be specified multiple times) ───────────────────────────────
    mcp_tools: Optional[list[str]] = typer.Option(
        None, "--mcp",
        help="MCP tool name to append to all agents. May be specified multiple times.",
    ),
    http_tools: Optional[list[str]] = typer.Option(
        None, "--http",
        help="HTTP tool name to append to all agents (placeholder URL generated). May be specified multiple times.",
    ),
    agent_tools: Optional[list[str]] = typer.Option(
        None, "--agent",
        help="Agent-call tool name to append to all agents (placeholder service URL generated). May be specified multiple times.",
    ),
):
    """
    Launch the interactive wizard to generate project.yaml.

    When no v2 flags are supplied, this command runs a step-by-step interactive
    wizard.  When any v2 flag is supplied (``--withPlanner``, ``--agents``, etc.)
    the wizard is skipped and the config is produced directly from the flags.

    Example::

        agentforge init
        agentforge init --output ./my-project
        agentforge init --withPlanner --agents alpha,beta --mcp foo --http bar
        agentforge init --withOrchestrator --orchestratorKind rule --agents sql
    """
    target = output / "project.yaml"
    if target.exists() and not force:
        console.print(f"[yellow]project.yaml already exists at {target}. Use --force to overwrite.[/yellow]")
        raise typer.Exit(1)

    # ── Validate orchestratorKind ─────────────────────────────────────────────
    if orchestrator_kind is not None and orchestrator_kind not in ORCHESTRATOR_KIND_CHOICES:
        raise typer.BadParameter(
            f"Invalid orchestratorKind '{orchestrator_kind}'. "
            f"Choose one of: {', '.join(ORCHESTRATOR_KIND_CHOICES)}",
            param_hint="--orchestratorKind",
        )

    # ── Enforce mutual exclusion (CLI layer) ──────────────────────────────────
    entry_type = _check_entry_mutual_exclusion(
        with_intent_router, with_passthrough, with_direct_input
    )
    pattern = _check_pattern_mutual_exclusion(
        with_react_agent, with_workflow, with_fanout, with_orchestrator, with_planner
    )

    # ── Decide execution mode ─────────────────────────────────────────────────
    v2_flags_given = _any_v2_flag_given(
        entry_type, pattern, orchestrator_kind, agents_csv, mcp_tools, http_tools, agent_tools
    )

    if v2_flags_given:
        # Non-interactive flag-driven mode.
        project_name = name or _DEFAULT_PROJECT_NAME

        patch = flags_to_config_patch(
            entry_type=entry_type,
            pattern=pattern,
            orchestrator_kind=orchestrator_kind,
            agents_csv=agents_csv,
            mcp_tools=mcp_tools,
            http_tools=http_tools,
            agent_tools=agent_tools,
        )

        try:
            config = _build_config_from_flags(project_name, patch)
        except Exception as exc:
            console.print(f"[red]Configuration error:[/red] {exc}")
            raise typer.Exit(2) from exc

        output.mkdir(parents=True, exist_ok=True)
        dump(config, target)
        console.print(f"[green]✓[/green] project.yaml written to [bold]{target}[/bold]")
        console.print("Run [bold]agentforge new[/bold] to scaffold your project.")
    else:
        # Interactive wizard mode (original behaviour, unchanged).
        console.print(Panel("[bold green]agentforge init[/bold green] — Agentic Project Wizard", expand=False))
        config = run_wizard()              # returns ProjectConfig
        output.mkdir(parents=True, exist_ok=True)
        dump(config, target)
        console.print(f"[green]✓[/green] project.yaml written to [bold]{target}[/bold]")
        console.print("Run [bold]agentforge new[/bold] to scaffold your project.")
