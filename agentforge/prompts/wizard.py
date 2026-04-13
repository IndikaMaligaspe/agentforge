"""
Full interactive wizard for generating a complete project.yaml configuration.

The wizard is decomposed into composable step functions — one per config section.
Each step function takes a partial dict and returns an updated partial dict, making
individual steps independently testable without running the full wizard.
"""
import questionary
from rich.console import Console
from rich.table import Table

from ..schema.models import (
    ProjectConfig, ProjectMetadata, AgentConfig,
    DatabaseConfig, WorkflowConfig, APIConfig,
    ObservabilityConfig, SecurityConfig, CORSConfig, CiConfig, DevelopmentConfig
)
from .questions import (
    ask_agent_config, ask_project_metadata, ask_database_config,
    ask_workflow_config, ask_api_config, ask_observability_config,
    ask_security_config, ask_ci_config, ask_development_config
)

console = Console()


# ── Composable step functions ─────────────────────────────────────────────────
# Each step takes a partial dict (accumulated wizard state) and returns a new
# dict with the step's keys merged in. Steps are pure with respect to their
# return value: same inputs → same outputs (subject to questionary responses).

def step_metadata(partial: dict) -> dict:
    """Step 1 — Collect project metadata and merge into partial dict."""
    metadata_dict = ask_project_metadata()
    return {**partial, "metadata": metadata_dict}


def step_agents(partial: dict) -> dict:
    """Step 2 — Collect one or more agent definitions and merge into partial dict."""
    num_agents = questionary.text(
        "How many agents?",
        default="1",
        validate=lambda v: v.isdigit() and 1 <= int(v) <= 10 or "Must be a number between 1 and 10",
    ).ask()

    agents = []
    for i in range(int(num_agents)):
        console.print(f"\n[bold]Agent {i+1}[/bold]")
        agent = ask_agent_config(existing_keys={a.key for a in agents})
        agents.append(agent)

    return {**partial, "agents": agents}


def step_database(partial: dict) -> dict:
    """Step 3 — Collect database configuration and merge into partial dict."""
    database_dict = ask_database_config()
    return {**partial, "database": database_dict}


def step_workflow(partial: dict) -> dict:
    """Step 4 — Collect workflow configuration and merge into partial dict.

    Reads agent_keys from the accumulated partial dict so the workflow step
    can present the correct default_intent choices.
    """
    agents = partial.get("agents", [])
    agent_keys = [a.key for a in agents]
    workflow_dict = ask_workflow_config(agent_keys)
    return {**partial, "workflow": workflow_dict}


def step_api(partial: dict) -> dict:
    """Step 5 — Collect API configuration and merge into partial dict."""
    api_dict = ask_api_config()
    return {**partial, "api": api_dict}


def step_observability(partial: dict) -> dict:
    """Step 6 — Collect observability configuration and merge into partial dict."""
    observability_dict = ask_observability_config()
    return {**partial, "observability": observability_dict}


def step_security(partial: dict) -> dict:
    """Step 7 — Collect security configuration and merge into partial dict."""
    security_dict = ask_security_config()
    return {**partial, "security": security_dict}


def step_development(partial: dict) -> dict:
    """Step 8 — Collect development tooling configuration and merge into partial dict."""
    development_dict = ask_development_config()
    return {**partial, "development": development_dict}


def step_ci(partial: dict) -> dict:
    """Step 9 — Collect CI configuration and merge into partial dict."""
    ci_dict = ask_ci_config()
    return {**partial, "ci": ci_dict}


def build_config(partial: dict) -> ProjectConfig:
    """Construct a validated ProjectConfig from the accumulated partial dict.

    Converts raw dicts for each sub-section into their typed model instances
    before constructing the root ProjectConfig.
    """
    agents = partial.get("agents", [])
    metadata_raw = partial.get("metadata", {})
    database_raw = partial.get("database", {})
    workflow_raw = partial.get("workflow", {})
    api_raw = partial.get("api", {})
    observability_raw = partial.get("observability", {})
    security_raw = partial.get("security", {})
    ci_raw = partial.get("ci", {})
    development_raw = partial.get("development", {})

    return ProjectConfig(
        metadata=ProjectMetadata(**metadata_raw) if isinstance(metadata_raw, dict) else metadata_raw,
        agents=agents,
        database=DatabaseConfig(**database_raw) if isinstance(database_raw, dict) else database_raw,
        workflow=WorkflowConfig(**workflow_raw) if isinstance(workflow_raw, dict) else workflow_raw,
        api=APIConfig(**api_raw) if isinstance(api_raw, dict) else api_raw,
        observability=ObservabilityConfig(**observability_raw) if isinstance(observability_raw, dict) else observability_raw,
        security=SecurityConfig(**security_raw) if isinstance(security_raw, dict) else security_raw,
        ci=CiConfig(**ci_raw) if isinstance(ci_raw, dict) else ci_raw,
        development=DevelopmentConfig(**development_raw) if isinstance(development_raw, dict) else development_raw,
        enable_provider_registry=False,
    )


# ── Orchestrator ──────────────────────────────────────────────────────────────

def run_wizard() -> ProjectConfig:
    """
    Run the full 10-step interactive wizard to generate a ProjectConfig.

    Steps:
    1. Project Metadata
    2. Agents
    3. Database
    4. Workflow
    5. API
    6. Observability
    7. Security
    8. Development
    9. CI
    10. Review & Confirm
    """
    partial: dict = {}

    console.print("\n[bold]Step 1 — Project Metadata[/bold]")
    partial = step_metadata(partial)

    console.print("\n[bold]Step 2 — Agents[/bold]")
    partial = step_agents(partial)

    console.print("\n[bold]Step 3 — Database[/bold]")
    partial = step_database(partial)

    console.print("\n[bold]Step 4 — Workflow[/bold]")
    partial = step_workflow(partial)

    console.print("\n[bold]Step 5 — API[/bold]")
    partial = step_api(partial)

    console.print("\n[bold]Step 6 — Observability[/bold]")
    partial = step_observability(partial)

    console.print("\n[bold]Step 7 — Security[/bold]")
    partial = step_security(partial)

    console.print("\n[bold]Step 8 — Development[/bold]")
    partial = step_development(partial)

    console.print("\n[bold]Step 9 — CI[/bold]")
    partial = step_ci(partial)

    config = build_config(partial)

    console.print("\n[bold]Step 10 — Review & Confirm[/bold]")
    _show_summary(config)

    confirmed = questionary.confirm("Is this configuration correct?", default=True).ask()
    if not confirmed:
        if questionary.confirm("Start over?", default=False).ask():
            return run_wizard()

    return config


def _show_summary(config: ProjectConfig) -> None:
    """Display a summary of the configuration."""
    table = Table(title=f"Project: {config.metadata.name}")

    table.add_column("Section", style="cyan")
    table.add_column("Details", style="green")

    table.add_row(
        "Metadata",
        f"Name: {config.metadata.name}\n"
        f"Description: {config.metadata.description}\n"
        f"Python: {config.metadata.python_version}"
    )

    agents_details = "\n".join(
        f"• {a.key} ({a.class_name}) - {len(a.tools)} tools"
        for a in config.agents
    )
    table.add_row("Agents", agents_details)

    table.add_row(
        "Database",
        f"Backend: {config.database.backend.value}\n"
        f"Tables: {', '.join(config.database.tables) if config.database.tables else 'None'}"
    )

    table.add_row(
        "Workflow",
        f"Default intent: {config.workflow.default_intent}\n"
        f"Feedback loop: {'Enabled' if config.workflow.enable_feedback_loop else 'Disabled'}\n"
        f"Validation node: {'Enabled' if config.workflow.enable_validation_node else 'Disabled'}"
    )

    table.add_row(
        "API",
        f"Title: {config.api.title}\n"
        f"CORS: {', '.join(str(o) for o in config.api.cors.origins)}"
    )

    table.add_row(
        "Observability",
        f"Tracing: {'Enabled' if config.observability.enable_tracing else 'Disabled'}"
    )

    table.add_row(
        "Security",
        f"Auth: {'Enabled' if config.security.enable_auth else 'Disabled'}\n"
        f"IP pseudonymization: {'Enabled' if config.security.enable_ip_pseudonymization else 'Disabled'}"
    )

    table.add_row(
        "Development",
        f"Pre-commit: {'Enabled' if config.development.pre_commit else 'Disabled'}"
    )

    table.add_row(
        "CI",
        f"Provider: {config.ci.provider}\n"
        f"Python: {config.ci.python_version}\n"
        f"Installer: {config.ci.installer}"
    )

    console.print(table)
