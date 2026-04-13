"""
Pydantic v2 models for project.yaml — agentforge configuration schema.

This module defines the complete schema for the project.yaml configuration file,
which is the single source of truth for agentforge project scaffolding. The schema
uses Pydantic v2 for validation, type safety, and serialization.

The schema is organized hierarchically:
- ProjectConfig (root model)
  - ProjectMetadata (project identity)
  - AgentConfig (one or more agents)
    - ToolConfig (optional tools for each agent)
  - DatabaseConfig (database connection settings)
  - WorkflowConfig (LangGraph workflow options)
  - APIConfig (FastAPI settings)
    - CORSConfig (CORS settings)
  - ObservabilityConfig (logging and tracing)
  - SecurityConfig (auth and sanitization)
  - CiConfig (CI provider settings)
  - DevelopmentConfig (local development tooling)
  - TestingConfig (eval framework and benchmark options)

Each model includes field-level validation and documentation.
"""
from __future__ import annotations

import warnings
from enum import Enum
from typing import Annotated, Literal
from pydantic import (
    BaseModel, Field, field_validator, model_validator,
    AnyHttpUrl, StringConstraints,
)


# ── Enums ────────────────────────────────────────────────────────────────────

class DBBackend(str, Enum):
    """
    Supported database backends for the scaffolded project.

    These values determine which database-specific code is generated
    in the mcp_server.py template and which dependencies are added
    to requirements.txt.
    """
    POSTGRES   = "postgres"
    SQLITE     = "sqlite"
    MYSQL      = "mysql"
    MSSQL      = "mssql"
    BIGQUERY   = "bigquery"

class LLMModel(str, Enum):
    """
    Supported LLM models for agents and router nodes.

    These model identifiers are used directly in the LangChain
    ChatOpenAI constructor and must match the provider's API.
    """
    GPT4O         = "gpt-4o"
    GPT4O_MINI    = "gpt-4o-mini"
    GPT4_TURBO    = "gpt-4-turbo"
    CLAUDE_3_5    = "claude-3-5-sonnet-20241022"
    CLAUDE_3_HAIKU = "claude-3-haiku-20240307"
    GEMINI_PRO    = "gemini-pro"
    OLLAMA_LLAMA3 = "ollama/llama3"


# ── Leaf models ───────────────────────────────────────────────────────────────

# Type aliases with validation constraints
SlugStr = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$", min_length=1, max_length=64)]
"""
Type for slug strings (lowercase with underscores).
Used for project names, agent keys, and other identifiers.
Must start with a lowercase letter, followed by lowercase letters, numbers, or underscores.
"""

ClassNameStr = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Za-z0-9]*$", min_length=1, max_length=128)]
"""
Type for Python class names (PascalCase).
Used for agent class names and other Python class identifiers.
Must start with an uppercase letter, followed by letters or numbers.
"""


class ToolConfig(BaseModel):
    """A single LangChain / MCP tool wired into an agent."""
    name: str = Field(..., description="Python identifier used as tool function name")
    description: str = Field(..., description="Tool description shown to the LLM")
    # Optional: MCP tool reference (if tool is exposed by mcp_server)
    mcp_resource: str | None = Field(None, description="e.g. 'execute_sql' from mcp_server")


class AgentConfig(BaseModel):
    """One concrete agent scaffolded under agents/<key>_agent.py"""
    key: SlugStr = Field(..., description="Intent routing key, e.g. 'sql'")
    class_name: ClassNameStr = Field(..., description="Python class name, e.g. 'SQLAgent'")
    llm_model: LLMModel = Field(LLMModel.GPT4O_MINI, description="LLM model identifier")
    system_prompt: str = Field(
        "You are a helpful assistant.",
        description="System prompt injected into the ReAct agent",
    )
    tools: list[ToolConfig] = Field(default_factory=list)
    needs_validation: bool = Field(
        False,
        description="If True, supervisor routes this agent's output through validation_node",
    )
    extra_return_keys: list[str] = Field(
        default_factory=list,
        description="Additional keys beyond success/output/error in run() return dict",
    )

    @field_validator("key")
    @classmethod
    def key_not_reserved(cls, v: str) -> str:
        """
        Validate that the agent key is not a reserved name.

        Reserved names are used for core components of the scaffolded project
        and cannot be used as agent keys to avoid naming conflicts.

        Args:
            v: The agent key to validate

        Returns:
            The validated agent key

        Raises:
            ValueError: If the key is in the reserved set
        """
        reserved = {"base", "registry", "supervisor", "router", "answer"}
        if v in reserved:
            raise ValueError(f"Agent key '{v}' is reserved. Choose another key.")
        return v


class DatabaseConfig(BaseModel):
    """DB pool configuration → mcp_server.py"""
    backend: DBBackend = Field(DBBackend.POSTGRES)
    tables: list[str] = Field(default_factory=list, description="Table names scaffolded into schema docs")
    connection_env_var: str = Field(
        "DATABASE_URL",
        description="Environment variable name that holds the connection string",
    )
    pool_size: int = Field(5, ge=1, le=100)
    max_overflow: int = Field(10, ge=0, le=200)
    use_alembic: bool = Field(False, description="Generate Alembic migration scaffold under backend/migrations/")


class WorkflowConfig(BaseModel):
    """LangGraph StateGraph options → workflow.py"""
    enable_feedback_loop: bool = Field(
        True,
        description="Wire feedback → improve_answer → feedback loop in the graph",
    )
    enable_validation_node: bool = Field(
        True,
        description="Keep validation_node in graph even when no agent needs_validation",
    )
    router_llm_model: LLMModel = Field(
        LLMModel.GPT4O_MINI,
        description="Fast model used in query_router_node classification",
    )
    router_llm_provider: Literal["openai", "anthropic"] = Field(
        "openai",
        description="LLM provider used in query_router_node classification.",
    )
    default_intent: str = Field(
        "sql",
        description="Fallback intent when router cannot classify query",
    )
    max_feedback_attempts: int = Field(3, ge=1, le=10)
    enable_checkpointing: bool = Field(
        False,
        description=(
            "Persist LangGraph state via AsyncPostgresSaver. "
            "Requires database.backend='postgres'."
        ),
    )

    @model_validator(mode="after")
    def warn_provider_model_mismatch(self) -> "WorkflowConfig":
        """
        Warn when router_llm_provider and router_llm_model look mismatched.

        Mixing is legal — a user might intentionally test a cross-provider
        combination — so we only warn, never raise.
        """
        model_val = self.router_llm_model.value
        provider = self.router_llm_provider
        if provider == "anthropic" and model_val.startswith("gpt-"):
            warnings.warn(
                f"router_llm_provider is 'anthropic' but router_llm_model is '{model_val}' "
                f"(a GPT model). This is likely a misconfiguration.",
                UserWarning,
                stacklevel=2,
            )
        elif provider == "openai" and model_val.startswith("claude-"):
            warnings.warn(
                f"router_llm_provider is 'openai' but router_llm_model is '{model_val}' "
                f"(a Claude model). This is likely a misconfiguration.",
                UserWarning,
                stacklevel=2,
            )
        return self


class CORSConfig(BaseModel):
    origins: list[AnyHttpUrl | Literal["*"]] = Field(default_factory=lambda: ["*"])
    allow_credentials: bool = False


class APIConfig(BaseModel):
    """FastAPI application options → main.py"""
    title: str = Field("My Agentic API")
    query_max_length: int = Field(2000, ge=50, le=10000)
    endpoints: list[str] = Field(
        default_factory=lambda: ["/query"],
        description="Endpoint paths to scaffold",
    )
    cors: CORSConfig = Field(default_factory=CORSConfig)


class ObservabilityConfig(BaseModel):
    """Logging + tracing → observability/logging.py + tracing.py"""
    enable_tracing: bool = Field(False, description="Wire Langfuse @observe decorators")
    tracing_provider: Literal["langfuse"] = Field("langfuse")
    context_fields: list[str] = Field(
        default_factory=lambda: ["request_id", "user_id", "session_id"],
        description="ContextVar names injected into every log line",
    )
    log_rotation_bytes: int = Field(10_485_760, description="10 MB default")
    log_backup_count: int = Field(5)
    structured_logging: bool = Field(
        False,
        description="Use structlog for JSON logging in the scaffolded project.",
    )


class SecurityConfig(BaseModel):
    """Auth + sanitizer → security/auth.py"""
    auth_type: Literal["none", "api_key", "jwt"] = Field(
        "none",
        description="Authentication strategy: none (open), api_key, or jwt",
    )
    api_key_env_var: str = Field("API_KEY", description="Env var holding the secret key")
    enable_ip_pseudonymization: bool = Field(
        False,
        description="Hash client IPs before logging in logging_middleware.py",
    )
    jwt_algorithm: Literal["HS256", "RS256"] | None = Field(
        None,
        description="JWT signing algorithm. Required when auth_type='jwt'.",
    )
    jwt_issuer: str | None = Field(
        None,
        description="Expected JWT issuer claim (iss). Used as default in generated settings.",
    )
    jwt_audience: str | None = Field(
        None,
        description="Expected JWT audience claim (aud). Used as default in generated settings.",
    )
    jwks_url: str | None = Field(
        None,
        description="JWKS endpoint URL. Required when jwt_algorithm='RS256'.",
    )

    @model_validator(mode="before")
    @classmethod
    def _translate_legacy_enable_auth(cls, data: object) -> object:
        """Accept the old enable_auth bool field and translate to auth_type for backwards compat."""
        if not isinstance(data, dict):
            return data
        if "enable_auth" in data and "auth_type" not in data:
            data = dict(data)
            data["auth_type"] = "api_key" if data.pop("enable_auth") else "none"
        elif "enable_auth" in data:
            data = dict(data)
            data.pop("enable_auth")
        return data

    @model_validator(mode="after")
    def _validate_jwt_fields(self) -> "SecurityConfig":
        """Cross-field validation for JWT auth configuration."""
        if self.auth_type == "jwt":
            if self.jwt_algorithm is None:
                raise ValueError(
                    "security.jwt_algorithm is required when auth_type='jwt'. "
                    "Set jwt_algorithm to 'HS256' or 'RS256'."
                )
            if self.jwt_algorithm == "RS256" and not self.jwks_url:
                raise ValueError(
                    "security.jwks_url is required when jwt_algorithm='RS256'. "
                    "Provide the JWKS endpoint URL (e.g. https://example.com/.well-known/jwks.json)."
                )
        return self

    @property
    def enable_auth(self) -> bool:
        """True when auth is active (api_key or jwt). Kept for template backwards compat."""
        return self.auth_type != "none"


class CiConfig(BaseModel):
    """GitHub Actions CI scaffold options."""
    provider: Literal["github", "none"] = "none"
    python_version: str = "3.12"
    installer: Literal["uv", "pip", "poetry"] = "uv"


class DevelopmentConfig(BaseModel):
    """Local development tooling scaffold options."""
    pre_commit: bool = Field(False, description="Generate .pre-commit-config.yaml with ruff and common hooks")


class TestingConfig(BaseModel):
    """Opt-in evaluation framework and benchmark scaffold options."""
    __test__ = False  # tell pytest this is not a test class
    eval_framework: Literal["none", "deepeval"] = Field(
        "none",
        description="Evaluation framework to use. 'deepeval' enables the benchmark scaffold.",
    )
    enable_benchmarks: bool = Field(
        False,
        description=(
            "Generate DeepEval benchmark scaffold under backend/tests/benchmarks/. "
            "Requires eval_framework='deepeval'."
        ),
    )

    @model_validator(mode="after")
    def check_benchmarks_require_deepeval(self) -> "TestingConfig":
        """Benchmarks can only be enabled when an eval framework is selected."""
        if self.enable_benchmarks and self.eval_framework == "none":
            raise ValueError(
                "testing.enable_benchmarks=True requires testing.eval_framework='deepeval'. "
                "Set eval_framework to 'deepeval' to enable the benchmark scaffold."
            )
        return self


class ProjectMetadata(BaseModel):
    """Top-level project identity."""
    name: SlugStr = Field(..., description="Python package / GitHub repo name")
    description: str = Field("An agentic project scaffolded by agentforge")
    python_version: str = Field("3.11", pattern=r"^\d+\.\d+$")
    author: str = Field("Your Name")
    email: str = Field("you@example.com")


class ProjectConfig(BaseModel):
    """
    Root model — the full project.yaml document.

    Example project.yaml:
    ----------------------
    metadata:
      name: my_agent_api
      description: My first agentic project
      python_version: "3.11"

    agents:
      - key: sql
        class_name: SQLAgent
        llm_model: gpt-4o-mini
        tools:
          - name: execute_sql
            description: Run a SQL query against the database
            mcp_resource: execute_sql
        needs_validation: true

    database:
      backend: postgres
      tables: [orders, customers, products]

    workflow:
      enable_feedback_loop: true
      enable_validation_node: true
      default_intent: sql
      router_llm_provider: openai   # default; set "anthropic" to use ChatAnthropic

    api:
      title: My Agentic API
      query_max_length: 2000
      cors:
        origins: ["http://localhost:3000"]

    observability:
      enable_tracing: true
      structured_logging: false     # default; set true to use structlog JSON logging

    security:
      auth_type: api_key
      api_key_env_var: MY_API_KEY

    ci:
      provider: github              # default: none (opt-in)
      python_version: "3.12"
      installer: uv                 # uv | pip | poetry

    development:
      pre_commit: true              # default: false (opt-in)

    testing:
      eval_framework: deepeval      # default: none (opt-in)
      enable_benchmarks: true       # default: false (opt-in)

    enable_provider_registry: false  # default; set true to generate backend/config/provider_registry.py
    """
    metadata: ProjectMetadata
    agents: list[AgentConfig] = Field(..., min_length=1)
    database: DatabaseConfig = Field(default_factory=lambda: DatabaseConfig())  # type: ignore[call-arg]
    workflow: WorkflowConfig = Field(default_factory=lambda: WorkflowConfig())  # type: ignore[call-arg]
    api: APIConfig = Field(default_factory=lambda: APIConfig())  # type: ignore[call-arg]
    observability: ObservabilityConfig = Field(default_factory=lambda: ObservabilityConfig())  # type: ignore[call-arg]
    security: SecurityConfig = Field(default_factory=lambda: SecurityConfig())  # type: ignore[call-arg]
    ci: CiConfig = Field(default_factory=lambda: CiConfig())  # type: ignore[call-arg]
    development: DevelopmentConfig = Field(default_factory=lambda: DevelopmentConfig())  # type: ignore[call-arg]
    testing: TestingConfig = Field(default_factory=lambda: TestingConfig())  # type: ignore[call-arg]
    enable_provider_registry: bool = Field(
        False,
        description="Generate backend/config/provider_registry.py in the scaffolded project.",
    )

    @model_validator(mode="after")
    def check_default_intent_registered(self) -> "ProjectConfig":
        """
        Validate that the default intent is registered as an agent key.

        This ensures that the workflow's default_intent refers to an actual agent
        that exists in the project configuration. Without this validation, the
        router node might default to a non-existent agent.

        Returns:
            The validated ProjectConfig instance

        Raises:
            ValueError: If the default_intent is not in the list of agent keys
        """
        agent_keys = {a.key for a in self.agents}
        if self.workflow.default_intent not in agent_keys:
            raise ValueError(
                f"workflow.default_intent='{self.workflow.default_intent}' "
                f"is not in agents keys: {agent_keys}"
            )
        return self

    @model_validator(mode="after")
    def check_validation_node_consistency(self) -> "ProjectConfig":
        """
        Ensure validation node configuration is consistent with agent requirements.

        If any agent has needs_validation=True, the workflow must have
        enable_validation_node=True. This prevents a configuration where an agent
        expects validation but the validation node is disabled in the workflow.

        Returns:
            The validated ProjectConfig instance

        Raises:
            ValueError: If any agent needs validation but the validation node is disabled
        """
        needs = any(a.needs_validation for a in self.agents)
        if needs and not self.workflow.enable_validation_node:
            raise ValueError(
                "workflow.enable_validation_node must be True when any agent has needs_validation=True"
            )
        return self

    @model_validator(mode="after")
    def check_checkpointing_requires_postgres(self) -> "ProjectConfig":
        """
        Enforce that LangGraph checkpointing is only enabled with a PostgreSQL backend.

        AsyncPostgresSaver is hard-wired to PostgreSQL; attempting to use it with
        sqlite, mysql, or any other backend will fail at runtime.  Reject the
        configuration early with an actionable message.

        Returns:
            The validated ProjectConfig instance

        Raises:
            ValueError: If enable_checkpointing is True and database.backend is not postgres
        """
        if self.workflow.enable_checkpointing and self.database.backend != DBBackend.POSTGRES:
            raise ValueError(
                f"workflow.enable_checkpointing requires database.backend='postgres' "
                f"(got '{self.database.backend.value}')"
            )
        return self
