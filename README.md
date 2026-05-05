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
agentforge new --git-init  # Run git init + initial commit after scaffolding
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
├── .env.example                       ← sectioned with === HEADER === blocks
├── .gitignore
├── .gitleaks.toml                     ← always generated; secret-scan rules
├── .secretscanignore                  ← always generated; per-file exclusions
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
    ├── config/
    │   └── settings.py                ← if enable_settings_module OR multi_tenancy.enabled OR stores declared
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
    ├── middleware/
    │   ├── __init__.py
    │   ├── logging_middleware.py
    │   ├── permission_gate.py         ← if security.auth_type == "jwt"
    │   └── account_gate.py            ← if multi_tenancy.enabled
    │
    ├── observability/
    │   ├── __init__.py
    │   ├── logging.py
    │   └── tracing.py
    │
    ├── security/
    │   ├── __init__.py
    │   ├── auth.py
    │   ├── sanitizer.py
    │   └── prompt_secret_scanner.py   ← if security.enable_prompt_secret_scan
    │
    └── services/
        ├── credential_provider.py     ← if multi_tenancy.enabled
        ├── platform_db.py             ← if multi_tenancy.enabled AND credential_provider == "db"
        ├── bigquery_rest_client.py    ← if any store declares "bigquery" backend
        └── {name}_store.py            ← one file per declared StoreSpec
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
  enable_prompt_secret_scan: false # Emit prompt_secret_scanner.py
  permission_key: "__placeholder_permission" # Default claim key for permission_gate.py

development:
  type_checking: none # none | pyright | mypy — emits pyrightconfig.json when "pyright"

enable_settings_module: false # Emit backend/config/settings.py (Pydantic-Settings)

multi_tenancy:
  enabled: false # Master switch for the tenancy stack
  credential_provider: env # env | db
  account_scoping_header: "X-Account-Id" # Header used to scope requests to a tenant
  platform_db_assembled_dsn: true # Assemble per-tenant DSN from parts rather than a single URL

stores: [] # List of StoreSpec blocks (see "Storage" section below)
```

## Optional features

The scaffolder exposes opt-in feature flags. All default to `none` / `False`, so existing `project.yaml` files regenerate unchanged.

### `observability.structured_logging` (default: `false`)

When enabled, generates `backend/observability/logging.py` using [structlog](https://www.structlog.org/) for JSON-structured logs, plus a companion smoke test at `backend/tests/test_structlog_setup.py`. The middleware is rewritten to use `clear_contextvars()` and structlog-native keyword logging. A `redact_secrets` processor is added to the structlog chain to strip sensitive values before emission. Recommended for production and Kubernetes deployments where log aggregators consume JSON.

### `workflow.router_llm_provider` (default: `"openai"`)

Selects the LLM provider used by `query_router_node.py` for intent classification. Set to `"anthropic"` to switch from `langchain_openai.ChatOpenAI` to `langchain_anthropic.ChatAnthropic`; `langchain-anthropic` is added to the generated `requirements.txt` when selected. Remember to also set `workflow.router_llm_model` to a matching model (e.g., `claude-3-haiku-20240307`) — agentforge warns at validation time if the provider and model appear mismatched.

### `enable_provider_registry` (default: `false`)

Generates `backend/config/provider_registry.py` and a sample `backend/config/providers.yaml` in the scaffolded project. The registry provides a generic abstraction for registering and looking up third-party data providers at runtime.

### `enable_settings_module` (default: `false`)

Generates `backend/config/settings.py` — a Pydantic-Settings module that loads all environment variables with type validation. Also generated automatically when `multi_tenancy.enabled` is `true` or when any `stores` are declared, since both features depend on environment-driven configuration.

```yaml
enable_settings_module: true
```

Generated file: `backend/config/settings.py`.

### `security.enable_prompt_secret_scan` (default: `false`)

Generates `backend/security/prompt_secret_scanner.py`, which provides a reusable scanner to detect accidental inclusion of secrets in LLM prompt strings before they leave the process. Wire it at any call site that builds prompts from user-supplied or environment-derived data.

```yaml
security:
  enable_prompt_secret_scan: true
```

Generated file: `backend/security/prompt_secret_scanner.py`.

### `security.permission_key` (default: `"__placeholder_permission"`)

Sets the JWT claim key that `backend/middleware/permission_gate.py` inspects when enforcing endpoint-level permissions. Only relevant when `security.auth_type: jwt` (which gates generation of `permission_gate.py`). Change this to the actual claim name your identity provider issues (e.g., `"permissions"`, `"scope"`, `"roles"`).

```yaml
security:
  auth_type: jwt
  permission_key: "permissions"
```

Generated file: `backend/middleware/permission_gate.py` (gated on `auth_type == "jwt"`).

### `development.type_checking` (default: `"none"`)

Controls static type-checker tooling. Accepted values: `"none"`, `"pyright"`, `"mypy"`.

Setting `"pyright"` generates a `pyrightconfig.json` at the project root with sensible defaults for the scaffolded layout. No extra file is generated for `"mypy"` — add your own `mypy.ini` as needed.

```yaml
development:
  type_checking: pyright
```

Generated file: `pyrightconfig.json` (gated on `type_checking == "pyright"`).

## Multi-tenancy

Set `multi_tenancy.enabled: true` to scaffold a complete per-tenant isolation stack. The four components ship as a unit: enabling the flag generates all of them together.

```yaml
multi_tenancy:
  enabled: true
  credential_provider: db   # env (default) | db
  account_scoping_header: "X-Account-Id"
  platform_db_assembled_dsn: true
```

| Field | Default | Description |
|-------|---------|-------------|
| `enabled` | `false` | Master switch; gates all four generated files. |
| `credential_provider` | `"env"` | `"env"` reads per-tenant credentials from environment variables; `"db"` fetches them from a credentials table, adding `platform_db.py`. |
| `account_scoping_header` | `"X-Account-Id"` | HTTP header the middleware reads to identify the calling tenant. |
| `platform_db_assembled_dsn` | `true` | When `true`, the platform DB DSN is assembled from `HOST`/`PORT`/`USER`/`PASS` parts rather than a single `DATABASE_URL`. |

Generated files:

| File | Condition |
|------|-----------|
| `backend/config/settings.py` | Always when `enabled` |
| `backend/services/credential_provider.py` | Always when `enabled` |
| `backend/services/platform_db.py` | `enabled` AND `credential_provider == "db"` |
| `backend/middleware/account_gate.py` | Always when `enabled` |

## Storage

Declare one or more store modules with the `stores` list. Each entry is a `StoreSpec` that generates a dedicated service module.

```yaml
stores:
  - name: audit_log
    backends: [memory, bigquery]
    default: bigquery
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `SlugStr` | required | Snake-case identifier; becomes the filename stem (`{name}_store.py`). |
| `backends` | `list` | `["memory"]` | One or more of `"memory"`, `"bigquery"`, `"postgres"`. |
| `default` | `str` | `"memory"` | Which backend is active at runtime; must appear in `backends`. |

Generated files:

| File | Condition |
|------|-----------|
| `backend/services/{name}_store.py` | One file per `StoreSpec` entry |
| `backend/services/bigquery_rest_client.py` | Any store includes `"bigquery"` in `backends` |
| `backend/config/settings.py` | Any stores are declared (also triggered by `enable_settings_module` or `multi_tenancy.enabled`) |

## Database migrations (Alembic)

Set `database.use_alembic: true` to scaffold an Alembic migration tree under `backend/migrations/`. The `database.backend` field controls which database driver appears in the generated `alembic.ini` and `requirements.txt`.

```yaml
database:
  backend: postgres   # postgres | mysql | sqlite
  use_alembic: true
```

Generated files: `alembic.ini`, `backend/migrations/env.py`, `backend/migrations/script.py.mako`.
Makefile targets `db-migrate` and `db-revision` are added when `use_alembic: true`.

## CI scaffolding

Set `ci.provider: github` to generate a GitHub Actions workflow at `.github/workflows/ci.yml`. The `installer` field controls which package manager installs dependencies.

```yaml
ci:
  provider: github       # github | none (default: none)
  python_version: "3.12"
  installer: uv          # uv | pip | poetry
```

## Pre-commit hooks

Set `development.pre_commit: true` to generate `.pre-commit-config.yaml` with ruff linting and formatting hooks.

```yaml
development:
  pre_commit: true   # default: false
```

## --git-init flag

Pass `--git-init` to `agentforge new` to run `git init` and create an initial commit after scaffolding. Skipped silently if `git` is not on `PATH`.

```bash
agentforge new --git-init
```

## Makefile

A `Makefile` is always generated. Targets are conditional: `db-migrate` / `db-revision` appear only when `database.use_alembic: true`; `test-benchmarks` appears only when `testing.enable_benchmarks: true`. Run `make help` in the generated project to see active targets.

The `run` target passes `--env-file .env` to the uvicorn invocation so that local environment variables are loaded automatically without a separate `source .env` step.

## Secret scanning

Two files are always generated regardless of other flags:

- `.gitleaks.toml` — Gitleaks configuration with rule sets tuned for Python agentic projects (API keys, JWT secrets, DSN strings).
- `.secretscanignore` — Per-file and per-pattern exclusions for the secret scanner, pre-populated with known-safe patterns such as example values and test fixtures.

These files are intentional starting points. Extend them to match the secret patterns and exclusions relevant to your project.

## MCP client

When any agent tool sets `mcp_resource`, agentforge generates `backend/services/mcp_client.py` using `langchain-mcp-adapters`. The client reads MCP server URLs from the `MCP_SERVERS` environment variable (JSON object).

```yaml
agents:
  - key: data
    class_name: DataAgent
    tools:
      - name: query_db
        description: Run a database query
        mcp_resource: query_db   # triggers MCP client generation
```

## DeepEval benchmarks

Set `testing.eval_framework: deepeval` and `testing.enable_benchmarks: true` to scaffold a benchmark suite under `backend/tests/benchmarks/`. No Slack integration is included.

```yaml
testing:
  eval_framework: deepeval   # default: none
  enable_benchmarks: true    # default: false
```

## JWT authentication

Set `security.auth_type: jwt` to scaffold JWT verification under `backend/security/`. Supports HS256 (symmetric secret) and RS256 (JWKS endpoint).

```yaml
# HS256 — symmetric secret read from JWT_SECRET env var
security:
  auth_type: jwt
  jwt_algorithm: HS256

# RS256 — public keys fetched from a JWKS endpoint
security:
  auth_type: jwt
  jwt_algorithm: RS256
  jwks_url: https://example.com/.well-known/jwks.json
  jwt_issuer: https://example.com
  jwt_audience: my-api
```

Generated files: `backend/security/jwt.py`, `backend/security/dtos.py`, `backend/security/jwt_settings.py`, `backend/security/__init__.py`, `backend/middleware/permission_gate.py`. The HS256 path adds `JWT_SECRET=` to `.env.example`; RS256 does not.

When `observability.structured_logging` is also enabled, `backend/security/jwt.py` binds `team_id`, `user_id`, and `request_id` as structlog context variables on every authenticated request, so these fields appear automatically in every downstream log line without manual threading.

## Memory / checkpointing

Set `workflow.enable_checkpointing: true` to scaffold LangGraph `AsyncPostgresSaver` checkpointing. Requires `database.backend: postgres`.

```yaml
database:
  backend: postgres
workflow:
  enable_checkpointing: true   # default: false
```

Generated files: `backend/graph/checkpointer.py`, `backend/config/memory_settings.py`. Adds `langgraph-checkpoint-postgres` and `psycopg[binary,pool]` to `requirements.txt`.

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

## Composable patterns (v2)

AgentForge v2 separates *entry* — how requests arrive at your service — from
*execution pattern* — what the graph does once a request lands. These two
dimensions are independent. Pick any entry type with any pattern. Existing
configs that predate v2 continue to work unchanged via schema auto-migration.

### Execution patterns

#### `react`

Use when you need a single agent that can call tools iteratively until it
reaches an answer. The agent runs a bounded ReAct loop: observe, think, act,
repeat. Well-suited for co-pilots and assistants that need to look things up
and synthesise a response.

```yaml
pattern: react

react:
  max_steps: 15
  tool_choice: auto
  temperature: 0.2

agents:
  - key: copilot
    class_name: CopilotAgent
    llm_model: gpt-4o
```

Full example: `examples/copilot.yaml`

#### `workflow`

Use when the execution path is fully deterministic and must follow a fixed
sequence of named steps. Supports human-in-the-loop (HITL) interrupts at any
step boundary. Best for approval workflows, multi-stage data pipelines, and
any flow where the step order is known at design time.

```yaml
pattern: workflow

workflow_sm:
  steps:
    - key: collect_inputs
      description: Gather and normalise campaign configuration
    - key: human_review
      description: Pause for a human reviewer to approve or reject
  hitl_before:
    - human_review

agents:
  - key: campaign_ops
    class_name: CampaignOpsAgent
    llm_model: gpt-4o-mini
```

Full example: `examples/workflow.yaml`

#### `fanout`

Use when multiple independent specialist agents should analyse the same input
concurrently and their results must be merged. The graph forks to all agents
in parallel and then applies a reducer. Ideal for parallel scoring pipelines
where each agent examines a different dimension of the same artifact.

```yaml
pattern: fanout

fanout:
  reducer: merge_dict
  results_field: analysis_scores

agents:
  - key: budget_analyzer
    class_name: BudgetAnalyzerAgent
    llm_model: gpt-4o-mini
```

Full example: `examples/fanout.yaml`

#### `orchestrator`

Use when a supervisor — either an LLM or a deterministic rule set — needs to
decide which specialist agent handles each request, and may chain multiple
agents sequentially or in parallel. This is the default pattern for configs
that predate v2. The `orchestrator.kind` field chooses between LLM-based and
rule-based routing.

```yaml
pattern: orchestrator

orchestrator:
  kind: rule   # or: llm

agents:
  - key: campaign_scorer
    class_name: CampaignScorerAgent
    llm_model: gpt-4o-mini
```

Full example: `examples/assistant.yaml`

#### `planner`

Use when requests must be decomposed into a dependency graph of sub-tasks,
executed concurrently, and then validated for coverage before a final report
is composed. Supports automatic replanning when the validator detects gaps.
Best for open-ended research or analysis briefs where the step set is not
known in advance.

```yaml
pattern: planner

planner:
  max_replans: 2
  max_concurrency: 4
  precheck_enabled: true
  validator_enabled: true
  composer_enabled: true
  llm_model: gpt-4o
  llm_temperature: 0.0

agents:
  - key: researcher
    class_name: ResearcherAgent
    llm_model: gpt-4o-mini
```

Full example: `examples/planner.yaml`

### Entry types

The entry type controls what happens to a request before it reaches the
execution pattern. All three entry types work with any pattern.

| Use case | Entry type |
|----------|------------|
| Chatbot or API that receives free text and must classify intent before routing | `intent_router` |
| UI co-pilot or caller that already knows the target agent and supplies the intent | `passthrough` |
| Automation pipeline or internal service that sends structured parameters directly | `direct` |

```yaml
# LLM classifies free text and routes to the right agent
entry:
  type: intent_router

# Caller knows the intent; LLM only extracts structured inputs
entry:
  type: passthrough

# Structured params arrive directly; no LLM parsing at the entry
entry:
  type: direct
```

`entry` is optional. Configs that omit it remain valid and no entry node is
generated.

### Tool kinds

Every tool under `agents[].tools[]` must declare a `kind`. Existing configs
without `kind` are automatically assigned `kind: mcp` by the schema validator.

| Kind | Description |
|------|-------------|
| `mcp` | Calls a local MCP server resource; requires `mcp_resource`. |
| `http` | Calls an external HTTP endpoint; requires `url`, `method`, `auth_env_var`. |
| `agent` | Calls a remote AgentForge service; requires `service_url`, `agent_key`, `auth_env_var`. |

```yaml
tools:
  # MCP tool — internal data access via MCP server
  - kind: mcp
    name: fetch_campaign_metrics
    description: Retrieve aggregated campaign metrics
    mcp_resource: fetch_campaign_metrics

  # HTTP tool — external third-party API call
  - kind: http
    name: get_audience_insights
    description: Fetch audience segment breakdown from the insights API
    url: https://example.com/api/v1/audience-insights
    method: GET
    auth_env_var: INSIGHTS_API_KEY
    timeout_s: 15.0

  # Agent tool — delegate to a sibling AgentForge service
  - kind: agent
    name: analytics_check
    description: Run the analytics pipeline for the selected account
    service_url: https://example.com/analytics-service/
    agent_key: analytics_scorer
    auth_env_var: ANALYTICS_SERVICE_JWT
```

See `docs/migration_v1_to_v2.md` for upgrading existing configs and
`docs/flag_cheatsheet.md` for the full list of CLI flags.

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
