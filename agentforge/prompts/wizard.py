"""
Full interactive wizard for generating a complete project.yaml configuration.
"""
import questionary
from rich.console import Console
from rich.table import Table

from ..schema.models import (
    ProjectConfig, ProjectMetadata, AgentConfig, 
    DatabaseConfig, WorkflowConfig, APIConfig,
    ObservabilityConfig, SecurityConfig, CORSConfig
)
from .questions import (
    ask_agent_config, ask_project_metadata, ask_database_config,
    ask_workflow_config, ask_api_config, ask_observability_config,
    ask_security_config
)

console = Console()

def run_wizard() -> ProjectConfig:
    """
    Run the full 8-step interactive wizard to generate a ProjectConfig.
    
    Steps:
    1. Project Metadata
    2. Agents
    3. Database
    4. Workflow
    5. API
    6. Observability
    7. Security
    8. Review & Confirm
    """
    console.print("\n[bold]Step 1 — Project Metadata[/bold]")
    metadata_dict = ask_project_metadata()
    metadata = ProjectMetadata(**metadata_dict)
    
    console.print("\n[bold]Step 2 — Agents[/bold]")
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
    
    agent_keys = [a.key for a in agents]
    
    console.print("\n[bold]Step 3 — Database[/bold]")
    database_dict = ask_database_config()
    database = DatabaseConfig(**database_dict)
    
    console.print("\n[bold]Step 4 — Workflow[/bold]")
    workflow_dict = ask_workflow_config(agent_keys)
    workflow = WorkflowConfig(**workflow_dict)
    
    console.print("\n[bold]Step 5 — API[/bold]")
    api_dict = ask_api_config()
    api = APIConfig(**api_dict)
    
    console.print("\n[bold]Step 6 — Observability[/bold]")
    observability_dict = ask_observability_config()
    observability = ObservabilityConfig(**observability_dict)
    
    console.print("\n[bold]Step 7 — Security[/bold]")
    security_dict = ask_security_config()
    security = SecurityConfig(**security_dict)
    
    # Create the full config
    config = ProjectConfig(
        metadata=metadata,
        agents=agents,
        database=database,
        workflow=workflow,
        api=api,
        observability=observability,
        security=security,
    )
    
    console.print("\n[bold]Step 8 — Review & Confirm[/bold]")
    _show_summary(config)
    
    confirmed = questionary.confirm("Is this configuration correct?", default=True).ask()
    if not confirmed:
        if questionary.confirm("Start over?", default=False).ask():
            return run_wizard()
        # Otherwise, proceed with current config
    
    return config

def _show_summary(config: ProjectConfig) -> None:
    """Display a summary of the configuration."""
    table = Table(title=f"Project: {config.metadata.name}")
    
    table.add_column("Section", style="cyan")
    table.add_column("Details", style="green")
    
    # Metadata
    table.add_row(
        "Metadata",
        f"Name: {config.metadata.name}\n"
        f"Description: {config.metadata.description}\n"
        f"Python: {config.metadata.python_version}"
    )
    
    # Agents
    agents_details = "\n".join(
        f"• {a.key} ({a.class_name}) - {len(a.tools)} tools"
        for a in config.agents
    )
    table.add_row("Agents", agents_details)
    
    # Database
    table.add_row(
        "Database",
        f"Backend: {config.database.backend.value}\n"
        f"Tables: {', '.join(config.database.tables) if config.database.tables else 'None'}"
    )
    
    # Workflow
    table.add_row(
        "Workflow",
        f"Default intent: {config.workflow.default_intent}\n"
        f"Feedback loop: {'Enabled' if config.workflow.enable_feedback_loop else 'Disabled'}\n"
        f"Validation node: {'Enabled' if config.workflow.enable_validation_node else 'Disabled'}"
    )
    
    # API
    table.add_row(
        "API",
        f"Title: {config.api.title}\n"
        f"CORS: {', '.join(str(o) for o in config.api.cors.origins)}"
    )
    
    # Observability
    table.add_row(
        "Observability",
        f"Tracing: {'Enabled' if config.observability.enable_tracing else 'Disabled'}"
    )
    
    # Security
    table.add_row(
        "Security",
        f"Auth: {'Enabled' if config.security.enable_auth else 'Disabled'}\n"
        f"IP pseudonymization: {'Enabled' if config.security.enable_ip_pseudonymization else 'Disabled'}"
    )
    
    console.print(table)