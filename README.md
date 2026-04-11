# AgentForge

A CLI tool for scaffolding production-grade agentic Python projects.

## Overview

AgentForge extracts proven patterns from production agent systems and parameterizes them through a declarative YAML config (`project.yaml`) and an interactive terminal wizard. It helps you quickly bootstrap new agentic projects with best practices baked in.

This tool was created entirely using agentic engineering tools and references the architecture patterns from [multi-agent-chat-with-data](https://github.com/IndikaMaligaspe/multi-agent-chat-with-data), a production-grade implementation of a multi-agent system with data access capabilities.

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

## Optional features

The scaffolder exposes three opt-in feature flags for the generated project. All default to the pre-existing behaviour, so existing `project.yaml` files continue to work unchanged.

### `observability.structured_logging` (default: `false`)

When enabled, generates `backend/observability/logging.py` using [structlog](https://www.structlog.org/) for JSON-structured logs, plus a companion smoke test at `backend/tests/test_structlog_setup.py`. The middleware is rewritten to use `clear_contextvars()` and structlog-native keyword logging. Recommended for production and Kubernetes deployments where log aggregators consume JSON.

### `workflow.router_llm_provider` (default: `"openai"`)

Selects the LLM provider used by `query_router_node.py` for intent classification. Set to `"anthropic"` to switch from `langchain_openai.ChatOpenAI` to `langchain_anthropic.ChatAnthropic`; `langchain-anthropic` is added to the generated `requirements.txt` when selected. Remember to also set `workflow.router_llm_model` to a matching model (e.g., `claude-3-haiku-20240307`) — agentforge warns at validation time if the provider and model appear mismatched.

### `enable_provider_registry` (default: `false`)

Generates `backend/config/provider_registry.py` and a sample `backend/config/providers.yaml` in the scaffolded project. The registry provides a generic abstraction for registering and looking up third-party data providers at runtime.

### Customizing the answer shape

The scaffolded `backend/graph/nodes/answer_node.py` exposes a small
`_shape_answer(result_obj)` helper that turns an agent's raw result
dict into the user-facing answer payload. The default returns
`{"type": "text", "data": ...}`, which is intentionally minimal — your
project's frontend almost certainly wants something richer (tables,
charts, MDX, Slack blocks, ...). Edit `_shape_answer` in place to
produce whatever shape your client consumes; the function is the
single intentional extension point for output formatting, so you do
not need to touch the rest of the workflow.

Most projects pair `_shape_answer` with a widget schema defined in
`backend/models/widgets.py` — typically a Pydantic discriminated union
on a `type: Literal[...]` field, so frontend and backend share a
well-typed contract. Agentforge does not scaffold this file because
the widget vocabulary is entirely project-specific (table, chart,
card, metric, mdx, Slack blocks, Vega-Lite specs, ...) and any default
shapes would be wrong for every concrete project. Define the shapes
your frontend consumes yourself, import them into `answer_node.py`,
and have `_shape_answer` return instances. A typical starting point:

```python
# backend/models/widgets.py
from typing import Literal, Union
from pydantic import BaseModel, Field

class TextWidget(BaseModel):
    type: Literal["text"] = "text"
    data: str

class TableWidget(BaseModel):
    type: Literal["table"] = "table"
    columns: list[str]
    rows: list[list]

Widget = Union[TextWidget, TableWidget]  # extend as needed
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

#### Without hatch (plain venv)

If you prefer a vanilla virtualenv, the test suite needs the runtime
dependencies of *scaffolded* projects (fastapi, langgraph, langchain,
structlog, etc.) installed alongside agentforge itself. They live in
the optional `scaffold-test` extra:

```bash
python3.12 -m venv .venv
source .venv/bin/activate

# Install agentforge plus the scaffolded-project runtime deps used by
# the full test suite (test_scaffold_import.py walks every generated
# .py file and imports it for real, so it needs them on sys.path).
pip install -e '.[scaffold-test]'

pytest tests/
```

Without the `scaffold-test` extra, `tests/test_scaffold_import.py` will
skip with a clear message listing which packages are missing.

### Recent Improvements

The following improvements have been made to enhance the reliability and functionality of AgentForge:

1. **Complete Template Library**: Added all required Jinja2 templates for full project scaffolding:
   - `state.py.j2` — LangGraph `AgentState` TypedDict
   - `feedback_node.py.j2` — Feedback loop node with configurable max attempts
   - `validation_node.py.j2` — Validation node for agent response safety checks
   - `mcp_server.py.j2` — Database connection pool singleton (supports postgres, mysql, sqlite, mssql, bigquery)
   - `requirements.txt.j2` — Dependency file with conditional DB drivers and tracing libraries
   - `env.j2` — `.env.example` with all required environment variables
   - `gitignore.j2` — Standard Python `.gitignore`

2. **Template Context Enhancements**: The renderer now exposes comprehensive flat aliases alongside nested config dicts:
   - All `metadata.*` fields: `project_name`, `description`, `python_version`, `author`, `author_email`
   - All `workflow.*` fields: `default_intent`, `enable_feedback_loop`, `enable_validation_node`, `router_llm_model`, `max_feedback_attempts`
   - All `database.*` fields: `db_backend`, `db_tables`, `db_connection_env_var`, `db_pool_size`
   - All `observability.*` fields: `enable_tracing`, `tracing_provider`, `context_fields`, `log_rotation_bytes`, `log_backup_count`
   - All `security.*` fields: `enable_auth`, `api_key_env_var`, `enable_ip_pseudonymization`
   - All `api.*` fields: `cors_origins`, `query_max_length`, `allow_credentials`

3. **Template Rendering Error Handling**: Added robust error handling for template rendering:
   - Validation of template existence before rendering
   - Explicit handling of undefined variables in templates
   - Detailed error messages for troubleshooting

4. **GitHub CLI Integration**: Enhanced GitHub integration with:
   - Validation of GitHub CLI installation
   - Authentication status checking
   - Improved error handling for repository operations
   - Detailed error messages for failed operations

5. **Comprehensive Test Suite**: Added tests for:
   - Interactive wizard functionality
   - GitHub CLI integration
   - End-to-end integration tests

These improvements make AgentForge more robust, user-friendly, and maintainable.

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

## Tips and Best Practices

Here are some helpful tips for getting the most out of AgentForge:

1. **Start with a clear agent design**: Before scaffolding, define the responsibilities and capabilities of each agent in your system.

2. **Use the validation node**: For agents that produce potentially risky outputs (like SQL queries or code), enable the `needs_validation` flag.

3. **Customize system prompts**: Each agent can have a tailored system prompt that defines its personality and capabilities.

4. **Leverage the feedback loop**: The built-in feedback mechanism allows agents to improve their responses based on user feedback.

5. **Extend with custom tools**: Add domain-specific tools to your agents by implementing them in the agent files and registering them.

6. **Version your project.yaml**: Keep your project.yaml in version control to track changes to your agent system configuration.

7. **Start small, then expand**: Begin with a single agent, then gradually add more specialized agents as your system grows.

## License

MIT
