# AgentForge

A CLI tool for scaffolding production-grade agentic Python projects.

## Overview

AgentForge extracts proven patterns from production agent systems and parameterizes them through a declarative YAML config (`project.yaml`) and an interactive terminal wizard. It helps you quickly bootstrap new agentic projects with best practices baked in.

## Features

- Zero boilerplate for new agentic projects
- Type-safe, validated configuration
- Friendly interactive experience
- Idiomatic CLI
- Reproducible scaffolding
- Optional GitHub repo creation
- Modern Python packaging

## Installation

```bash
# Install from PyPI
pip install agentforge

# Or install from source
git clone https://github.com/yourusername/agentforge.git
cd agentforge
pip install -e .
```

## Quick Start

```bash
# Create a new project interactively
agentforge init

# Scaffold the project from project.yaml
agentforge new

# Add a new agent to an existing project
agentforge add agent

# Validate your project.yaml
agentforge validate

# Create a GitHub repository for your project
agentforge gh create
```

## Command Reference

### `agentforge init`

Launches an interactive wizard to create a `project.yaml` configuration file.

```bash
agentforge init
agentforge init --output ./my-project
agentforge init --force  # Overwrite existing project.yaml
```

### `agentforge new`

Scaffolds a complete project based on a `project.yaml` configuration file.

```bash
agentforge new
agentforge new --config ./custom-project.yaml
agentforge new --output ./my-project-dir
agentforge new --dry-run  # Preview files without writing
agentforge new --overwrite  # Overwrite existing files
```

### `agentforge add agent`

Adds a new agent to an existing project.

```bash
agentforge add agent
agentforge add agent --config ./project.yaml
agentforge add agent --output ./my-project-dir
```

### `agentforge validate`

Validates a `project.yaml` file without generating any files.

```bash
agentforge validate
agentforge validate --config ./custom-project.yaml
```

### `agentforge gh`

GitHub integration commands (requires GitHub CLI).

```bash
# Create a new GitHub repository
agentforge gh create
agentforge gh create --private
```

## Project Structure

AgentForge generates a well-structured project with:

- LangChain/LangGraph integration
- Agent registry with auto-discovery
- Workflow graph with routing, validation, and feedback
- FastAPI endpoints
- Structured logging and tracing
- Security middleware
- Database connectivity

### Generated Directory Structure

For a project named `my_agent_api` with agents `sql` and `analytics`:

```
my_agent_api/                          ← scaffolded output
├── .env.example
├── .gitignore
├── README.md
├── requirements.txt
│
└── backend/
    ├── main.py                        ← FastAPI lifespan + endpoints
    ├── mcp_server.py                  ← DB pool singleton
    │
    ├── agents/
    │   ├── __init__.py
    │   ├── base_agent.py              ← ABC contract
    │   ├── registry.py                ← AgentRegistry + @register_agent
    │   ├── sql_agent.py               ← rendered from agent.py.j2
    │   └── analytics_agent.py         ← rendered from agent.py.j2
    │
    ├── graph/
    │   ├── __init__.py
    │   ├── state.py                   ← AgentState TypedDict
    │   ├── workflow.py                ← LangGraph StateGraph
    │   └── nodes/
    │       ├── __init__.py
    │       ├── query_router_node.py
    │       ├── supervisor_node.py
    │       ├── answer_node.py
    │       ├── validation_node.py     ← only if enable_validation_node=True
    │       └── feedback_node.py       ← only if enable_feedback_loop=True
    │
    ├── observability/
    │   ├── __init__.py
    │   ├── logging.py
    │   └── tracing.py
    │
    ├── middleware/
    │   ├── __init__.py
    │   └── logging_middleware.py
    │
    └── security/
        ├── __init__.py
        ├── auth.py
        └── sanitizer.py
```

## Configuration Reference

The `project.yaml` file is the single source of truth for your project configuration. Here's a reference of the available options:

```yaml
metadata:
  name: my_agent_api # Required: Project name (slug format)
  description: My agentic project # Project description
  python_version: "3.11" # Python version (3.11 or 3.12)
  author: Your Name # Author name
  email: you@example.com # Author email

agents: # Required: At least one agent
  - key: sql # Intent routing key
    class_name: SQLAgent # Python class name
    llm_model: gpt-4o-mini # LLM model to use
    system_prompt: You are a helpful SQL assistant.
    tools: # Optional tools for this agent
      - name: execute_sql
        description: Run a SQL query against the database
        mcp_resource: execute_sql # Optional MCP resource reference
    needs_validation: true # Route through validation node?

database:
  backend: postgres # postgres, sqlite, mysql, mssql, bigquery
  tables: [orders, customers] # Table names for documentation
  connection_env_var: DATABASE_URL # Env var for connection string
  pool_size: 5 # Connection pool size

workflow:
  enable_feedback_loop: true # Add feedback → improve loop
  enable_validation_node: true # Include validation node
  router_llm_model: gpt-4o-mini # Model for intent classification
  default_intent: sql # Fallback intent
  max_feedback_attempts: 3 # Max feedback loop iterations

api:
  title: My Agentic API # API title
  query_max_length: 2000 # Max query length
  endpoints: ["/query"] # API endpoints
  cors:
    origins: ["http://localhost:3000"] # CORS origins
    allow_credentials: false # Allow credentials

observability:
  enable_tracing: true # Enable Langfuse tracing
  tracing_provider: langfuse # Tracing provider
  context_fields: # Context fields for logs
    - request_id
    - user_id
    - session_id
  log_rotation_bytes: 10485760 # 10 MB log rotation
  log_backup_count: 5 # Number of log backups

security:
  enable_auth: true # Enable API key auth
  api_key_env_var: API_KEY # Env var for API key
  enable_ip_pseudonymization: false # Hash IPs in logs
```

## Development

### Setup Development Environment

```bash
# Clone the repository
git clone https://github.com/yourusername/agentforge.git
cd agentforge

# Create a development environment with hatch
hatch env create

# Run tests
hatch run test

# Run linting
hatch run lint

# Run type checking
hatch run typecheck

# Format code
hatch run fmt
```

### Project Architecture

AgentForge follows a modular architecture:

- **CLI Layer**: Typer-based command-line interface
- **Schema Layer**: Pydantic v2 models for configuration validation
- **Template Layer**: Jinja2 templates for code generation
- **Rendering Engine**: Converts templates to code based on configuration
- **File Writer**: Writes rendered templates to disk
- **Interactive Prompts**: Questionary-based wizard for configuration

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

MIT
