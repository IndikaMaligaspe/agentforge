"""
Individual question builders for the interactive wizard.
"""
import questionary
from ..schema.models import AgentConfig, ToolConfig, LLMModel, DBBackend

def ask_agent_config(existing_keys: set[str] | None = None) -> AgentConfig:
    """Interactive prompt for creating a new agent configuration."""
    key = questionary.text(
        "Agent key (e.g. 'sql'):",
        validate=lambda v: v not in (existing_keys or set()) or "Key already exists",
    ).ask()

    class_name = questionary.text(
        "Agent class name:",
        default="".join(w.capitalize() for w in key.split("_")) + "Agent",
    ).ask()

    llm_model = questionary.select(
        "LLM model:",
        choices=[m.value for m in LLMModel],
        default=LLMModel.GPT4O_MINI.value,
    ).ask()

    system_prompt = questionary.text(
        "System prompt:", default="You are a helpful assistant."
    ).ask()

    needs_validation = questionary.confirm("Needs validation node?", default=False).ask()

    tools = []
    while questionary.confirm("Add a tool?", default=False).ask():
        tools.append(_ask_tool())

    return AgentConfig(
        key=key,
        class_name=class_name,
        llm_model=llm_model,
        system_prompt=system_prompt,
        needs_validation=needs_validation,
        tools=tools,
    )

def _ask_tool() -> ToolConfig:
    """Interactive prompt for creating a new tool configuration."""
    name = questionary.text("Tool name:").ask()
    description = questionary.text("Tool description:").ask()
    has_mcp = questionary.confirm("Is this an MCP resource?", default=False).ask()
    mcp_resource = questionary.text("MCP resource name:").ask() if has_mcp else None
    
    return ToolConfig(
        name=name,
        description=description,
        mcp_resource=mcp_resource,
    )

def ask_project_metadata():
    """Interactive prompt for project metadata."""
    name = questionary.text(
        "Project name:",
        validate=lambda v: bool(v) or "Name cannot be empty",
    ).ask()
    
    description = questionary.text(
        "Project description:",
        default="An agentic project scaffolded by agentforge",
    ).ask()
    
    python_version = questionary.select(
        "Python version:",
        choices=["3.11", "3.12"],
        default="3.11",
    ).ask()
    
    author = questionary.text(
        "Author name:",
        default="Your Name",
    ).ask()
    
    email = questionary.text(
        "Author email:",
        default="you@example.com",
    ).ask()
    
    return {
        "name": name,
        "description": description,
        "python_version": python_version,
        "author": author,
        "email": email,
    }

def ask_database_config():
    """Interactive prompt for database configuration."""
    backend = questionary.select(
        "Database backend:",
        choices=[b.value for b in DBBackend],
        default=DBBackend.POSTGRES.value,
    ).ask()
    
    tables_str = questionary.text(
        "Tables (comma-separated):",
        default="",
    ).ask()
    tables = [t.strip() for t in tables_str.split(",")] if tables_str else []
    
    connection_env_var = questionary.text(
        "Connection environment variable:",
        default="DATABASE_URL",
    ).ask()
    
    pool_size = questionary.text(
        "Pool size:",
        default="5",
        validate=lambda v: v.isdigit() and 1 <= int(v) <= 100 or "Must be a number between 1 and 100",
    ).ask()
    
    max_overflow = questionary.text(
        "Max overflow:",
        default="10",
        validate=lambda v: v.isdigit() and 0 <= int(v) <= 200 or "Must be a number between 0 and 200",
    ).ask()
    
    use_alembic = questionary.confirm(
        "Generate Alembic migration scaffold?",
        default=False,
    ).ask()

    return {
        "backend": backend,
        "tables": tables,
        "connection_env_var": connection_env_var,
        "pool_size": int(pool_size),
        "max_overflow": int(max_overflow),
        "use_alembic": use_alembic,
    }

def ask_workflow_config(agent_keys: list[str]):
    """Interactive prompt for workflow configuration."""
    enable_feedback_loop = questionary.confirm(
        "Enable feedback loop?",
        default=True,
    ).ask()
    
    enable_validation_node = questionary.confirm(
        "Enable validation node?",
        default=True,
    ).ask()
    
    default_intent = questionary.select(
        "Default intent:",
        choices=agent_keys,
        default=agent_keys[0] if agent_keys else None,
    ).ask()
    
    max_feedback_attempts = questionary.text(
        "Max feedback attempts:",
        default="3",
        validate=lambda v: v.isdigit() and 1 <= int(v) <= 10 or "Must be a number between 1 and 10",
    ).ask()
    
    return {
        "enable_feedback_loop": enable_feedback_loop,
        "enable_validation_node": enable_validation_node,
        "default_intent": default_intent,
        "max_feedback_attempts": int(max_feedback_attempts),
    }

def ask_api_config():
    """Interactive prompt for API configuration."""
    title = questionary.text(
        "API title:",
        default="My Agentic API",
    ).ask()
    
    query_max_length = questionary.text(
        "Query max length:",
        default="2000",
        validate=lambda v: v.isdigit() and 50 <= int(v) <= 10000 or "Must be a number between 50 and 10000",
    ).ask()
    
    cors_origins_str = questionary.text(
        "CORS origins (comma-separated URLs or *):",
        default="*",
    ).ask()
    
    return {
        "title": title,
        "query_max_length": int(query_max_length),
        "cors": {
            "origins": [o.strip() for o in cors_origins_str.split(",")],
            "allow_credentials": False,
        },
    }

def ask_observability_config():
    """Interactive prompt for observability configuration."""
    enable_tracing = questionary.confirm(
        "Enable tracing?",
        default=False,
    ).ask()
    
    context_fields_str = questionary.text(
        "Context fields (comma-separated):",
        default="request_id,user_id,session_id",
    ).ask()
    
    return {
        "enable_tracing": enable_tracing,
        "tracing_provider": "langfuse",
        "context_fields": [f.strip() for f in context_fields_str.split(",")],
        "log_rotation_bytes": 10_485_760,  # 10 MB
        "log_backup_count": 5,
    }

def ask_security_config():
    """Interactive prompt for security configuration."""
    enable_auth = questionary.confirm(
        "Enable authentication?",
        default=False,
    ).ask()
    
    api_key_env_var = questionary.text(
        "API key environment variable:",
        default="API_KEY",
    ).ask() if enable_auth else "API_KEY"
    
    enable_ip_pseudonymization = questionary.confirm(
        "Enable IP pseudonymization?",
        default=False,
    ).ask()
    
    return {
        "enable_auth": enable_auth,
        "api_key_env_var": api_key_env_var,
        "enable_ip_pseudonymization": enable_ip_pseudonymization,
    }