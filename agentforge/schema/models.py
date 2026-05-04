"""
Pydantic v2 models for project.yaml — agentforge configuration schema.

This module defines the complete schema for the project.yaml configuration file,
which is the single source of truth for agentforge project scaffolding. The schema
uses Pydantic v2 for validation, type safety, and serialization.

The schema is organized hierarchically:
- ProjectConfig (root model)
  - EntryConfig (how the graph receives work — v2)
  - ProjectMetadata (project identity)
  - AgentConfig (one or more agents)
    - ToolConfig (optional tools for each agent)
  - DatabaseConfig (database connection settings)
  - WorkflowConfig (LangGraph workflow options)
  - ReactConfig (per-pattern config for react pattern — v2)
  - StepConfig (one step in a workflow state machine — v2)
  - WorkflowStateMachineConfig (per-pattern config for workflow pattern — v2)
  - FanoutConfig (per-pattern config for fanout pattern — v2)
  - OrchestratorConfig (per-pattern config for orchestrator pattern — v2)
  - PlannerConfig (per-pattern config for planner pattern — v2)
  - StoreSpec (one store kind to scaffold — v2)
  - APIConfig (FastAPI settings)
    - CORSConfig (CORS settings)
  - ObservabilityConfig (logging and tracing)
  - SecurityConfig (auth and sanitization)
  - MultiTenancyConfig (multi-tenancy scaffold options)
  - CiConfig (CI provider settings)
  - DevelopmentConfig (local development tooling)
  - TestingConfig (eval framework and benchmark options)

Each model includes field-level validation and documentation.

Backwards compatibility
-----------------------
Configs that predate v2 (no `entry`, no `pattern` top-level keys) are
transparently rewritten at parse time by a ``model_validator(mode="before")``
into the equivalent v2 shape:

    entry.type = "intent_router"
    pattern    = "orchestrator"
    orchestrator.kind = "llm"

This preserves the existing ``query_router -> supervisor -> agents`` topology.
All new top-level fields default to ``None`` and are omitted from
``model_dump(exclude_none=True)``, so legacy round-trips are byte-clean.
"""
from __future__ import annotations

import warnings
from enum import Enum
from typing import Annotated, Any, Final, Literal, Union, get_args
from pydantic import (
    BaseModel, ConfigDict, Field, field_validator, model_validator,
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


# ── Tool tagged union (TODO-v2-7) ────────────────────────────────────────────

# Shared slug constraint for tool.name — must be a valid Python identifier prefix.
_ToolNameStr = Annotated[
    str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$", min_length=1, max_length=64)
]


class McpTool(BaseModel):
    """An MCP-backed tool connecting to an MCP server via langchain-mcp-adapters."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal["mcp"] = Field("mcp", description="Tool transport kind discriminator.")
    name: _ToolNameStr = Field(..., description="Python identifier used as tool function name.")
    description: str = Field(..., description="Tool description shown to the LLM.")
    # Optional reference to a resource exposed by mcp_server.py in the scaffolded project.
    mcp_resource: str | None = Field(None, description="e.g. 'execute_sql' from mcp_server.")


class HttpTool(BaseModel):
    """An HTTP(S) tool that calls an arbitrary REST endpoint using httpx."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal["http"] = Field(..., description="Tool transport kind discriminator.")
    name: _ToolNameStr = Field(..., description="Python identifier used as tool function name.")
    description: str = Field(..., description="Tool description shown to the LLM.")
    url: AnyHttpUrl = Field(..., description="Base URL of the REST endpoint.")
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = Field(
        "GET", description="HTTP method for the tool call."
    )
    auth_env_var: str | None = Field(
        None,
        description="Name of the env var holding the bearer token. Read at call time.",
    )
    timeout_s: float = Field(
        30.0,
        gt=0,
        le=600,
        description="Per-call HTTP timeout in seconds. Must be > 0 and <= 600.",
    )


class AgentTool(BaseModel):
    """A tool that calls another AgentForge-generated service over JWT-authenticated HTTP."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal["agent"] = Field(..., description="Tool transport kind discriminator.")
    name: _ToolNameStr = Field(..., description="Python identifier used as tool function name.")
    description: str = Field(..., description="Tool description shown to the LLM.")
    service_url: AnyHttpUrl = Field(
        ..., description="Base URL of the downstream AgentForge service."
    )
    agent_key: str = Field(
        ..., description="Identifies the downstream agent within the service."
    )
    auth_env_var: str | None = Field(
        None,
        description="Name of the env var holding the JWT bearer token. Read at call time.",
    )


# Tagged union — discriminated on the 'kind' field.
# The before-validator in ProjectConfig._inject_v2_defaults_for_legacy_configs
# ensures that any tool entry without a 'kind' key is rewritten to kind="mcp"
# before Pydantic attempts to resolve the discriminator.
Tool = Annotated[Union[McpTool, HttpTool, AgentTool], Field(discriminator="kind")]

# Backwards-compatibility alias: pre-v2-7 code that imported ToolConfig by name
# (tests, CLI prompts, etc.) continues to work — ToolConfig IS McpTool.
ToolConfig = McpTool


class AgentConfig(BaseModel):
    """One concrete agent scaffolded under agents/<key>_agent.py"""
    key: SlugStr = Field(..., description="Intent routing key, e.g. 'sql'")
    class_name: ClassNameStr = Field(..., description="Python class name, e.g. 'SQLAgent'")
    llm_model: LLMModel = Field(LLMModel.GPT4O_MINI, description="LLM model identifier")
    system_prompt: str = Field(
        "You are a helpful assistant.",
        description="System prompt injected into the ReAct agent",
    )
    tools: list[Tool] = Field(default_factory=list)
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
    enable_prompt_secret_scan: bool = Field(
        default=False,
        description=(
            "Emit prompt_secret_scanner.py module that LLM call sites can use to "
            "guard against accidentally including secrets in prompts. Pattern list is "
            "append-only — projects extend it; do not replace."
        ),
    )
    permission_key: str = Field(
        default="__placeholder_permission",
        description=(
            "Default permission claim key for the permission_gate middleware. "
            "Production projects should override this with the project-specific "
            "key (e.g. 'app:read'). The placeholder value emits a one-time "
            "warning at module-import time so deployments can't accidentally "
            "ship the default."
        ),
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


class MultiTenancyConfig(BaseModel):
    """Multi-tenancy configuration block.

    Off by default. When enabled, the scaffold emits:
      - platform_db.py (asyncpg pool helper) — TODO-5.5
      - credential_provider.py (Protocol + env/db impls + factory) — TODO-5.6
      - account_gate.py (FastAPI dependency) — TODO-5.7
      - settings.py (forced on) with platform-DB DSN assembly — TODO-5.4 / 5.8

    Items 1-4 must ship together as a unit; selecting `enabled=True` without
    them produces a half-built scaffold. The umbrella flag prevents that.
    """

    enabled: bool = Field(default=False)
    credential_provider: Literal["env", "db"] = Field(
        default="env",
        description=(
            "How tenant credentials are stored. 'env' reads from `.env` (Phase-1 "
            "single-tenant). 'db' uses an asyncpg connection to a platform DB "
            "with a per-tenant lookup."
        ),
    )
    account_scoping_header: str = Field(
        default="X-Account-Id",
        description=(
            "HTTP header that carries the active account id for tenant-scoped "
            "requests. The account_gate middleware reads this header and "
            "validates against the tenant's allowed accounts."
        ),
    )
    platform_db_assembled_dsn: bool = Field(
        default=True,
        description=(
            "When True (default), Settings.platform_db_url is assembled from "
            "PLATFORM_DB_HOST/USER/PW/PORT/NAME parts (with URL-encoding). "
            "When False, the explicit PLATFORM_DB_URL env var must be set."
        ),
    )


class CiConfig(BaseModel):
    """GitHub Actions CI scaffold options."""
    provider: Literal["github", "none"] = "none"
    python_version: str = "3.12"
    installer: Literal["uv", "pip", "poetry"] = "uv"


class DevelopmentConfig(BaseModel):
    """Local development tooling scaffold options."""
    pre_commit: bool = Field(False, description="Generate .pre-commit-config.yaml with ruff and common hooks")
    type_checking: Literal["none", "pyright", "mypy"] = Field(
        default="none",
        description=(
            "Type checker to scaffold a config for. 'pyright' emits "
            "pyrightconfig.json. 'mypy' is reserved for a future template. "
            "'none' (default) emits nothing — preserves existing scaffolds."
        ),
    )


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


# ── v2 pattern sub-configs ────────────────────────────────────────────────────

_PATTERN_LITERALS = Literal["react", "workflow", "fanout", "orchestrator", "planner"]
"""Canonical set of execution pattern names. Used as a type alias for field declarations."""

LEGACY_DEFAULT_PATTERN: Final[str] = "orchestrator"
"""The implicit pattern used for configs that predate the v2 `pattern` top-level key.
This is the single source of truth for the literal string — all other modules must
import this constant rather than hardcoding the string.
"""


def is_valid_pattern(name: str) -> bool:
    """Return True if *name* is a member of ``_PATTERN_LITERALS``.

    Uses ``typing.get_args`` so the check is always in sync with the
    ``_PATTERN_LITERALS`` Literal type and never needs a parallel list.

    Args:
        name: The pattern name to validate.

    Returns:
        ``True`` if *name* is one of the allowed pattern literals.
    """
    return name in get_args(_PATTERN_LITERALS)

_FLAGS_COMPATIBLE_PATTERNS: frozenset[str] = frozenset({"orchestrator", "react"})
"""Patterns that support workflow.enable_feedback_loop and enable_validation_node.
Derived as the complement of the non-interactive batch patterns in _PATTERN_LITERALS."""


def pattern_supports_feedback_loop(pattern: str | None) -> bool:
    """Return True if workflow.enable_feedback_loop / enable_validation_node are valid for this pattern.

    This is the single source of truth for pattern compatibility checks.
    Call sites should use this helper instead of testing membership in
    ``_FLAGS_COMPATIBLE_PATTERNS`` directly.

    Args:
        pattern: The pattern string from ``ProjectConfig.pattern``, or ``None``
            (no pattern set — treated as compatible).

    Returns:
        ``True`` when *pattern* is ``None`` or is one of the patterns that
        support feedback-loop / validation-node flags (currently ``"orchestrator"``
        and ``"react"``).
    """
    return pattern is None or pattern in _FLAGS_COMPATIBLE_PATTERNS


_ENTRY_TYPE_LITERALS = Literal["intent_router", "passthrough", "direct"]
"""Canonical set of entry type names. Used as a type alias for field declarations."""


class EntryConfig(BaseModel):
    """
    How the graph receives work (v2).

    - ``intent_router``: LLM parses free text and routes to an agent by intent
      (equivalent to the existing ``query_router_node`` topology).
    - ``passthrough``: Caller supplies the intent; LLM only extracts structured inputs.
    - ``direct``: Structured params come in directly — no LLM parsing at the entry.
    """
    type: _ENTRY_TYPE_LITERALS = Field(
        ...,
        description="Entry type: 'intent_router', 'passthrough', or 'direct'.",
    )
    screen_context_fields: list[str] | None = Field(
        None,
        description="Context variable names injected into the entry node prompt (optional).",
    )


class ReactConfig(BaseModel):
    """Per-pattern configuration for the ``react`` execution pattern (v2)."""
    max_steps: int = Field(12, ge=1, description="Maximum tool-call iterations before the loop terminates.")
    tool_choice: Literal["auto", "required"] = Field(
        "auto",
        description="LangChain tool_choice setting passed to the bound LLM.",
    )
    temperature: float = Field(
        0.0,
        ge=0.0,
        le=2.0,
        description="LLM sampling temperature for the ReAct agent. 0.0 means deterministic output.",
    )


class StepConfig(BaseModel):
    """
    One step in a deterministic workflow state machine (v2, ``pattern: workflow``).

    Each step becomes a node in the generated LangGraph ``StateGraph``.
    The ``key`` is the Python identifier used as the node name; ``description``
    is embedded in the generated module docstring for readability.
    """
    key: SlugStr = Field(
        ...,
        description=(
            "Slug-style identifier for this step (lowercase, underscores). "
            "Used as the LangGraph node name and the generated function name."
        ),
    )
    description: str = Field(
        "",
        description="Human-readable description of what this step does. Embedded in the generated docstring.",
    )


class WorkflowStateMachineConfig(BaseModel):
    """
    Per-pattern configuration for the ``workflow`` execution pattern (v2).

    A deterministic state-machine workflow with optional human-in-the-loop
    interrupts at named steps.

    ``steps`` defines the ordered sequence of nodes; the graph is wired as
    ``START → steps[0] → steps[1] → ... → steps[-1] → END``.

    ``hitl_before`` lists the step keys at which LangGraph should interrupt
    *before* executing that node (passed to ``.compile(interrupt_before=...)``).
    Every entry in ``hitl_before`` must reference a declared step key.
    """
    steps: list[StepConfig] = Field(
        default_factory=list,
        description=(
            "Ordered list of step nodes in the workflow. "
            "At least one step is required when pattern='workflow'. "
            "The graph is wired START → step[0] → ... → step[N-1] → END."
        ),
    )
    hitl_before: list[str] = Field(
        default_factory=list,
        description=(
            "Step keys at which LangGraph will interrupt before execution (HITL). "
            "Every entry must match a declared step key."
        ),
    )

    @model_validator(mode="after")
    def _validate_hitl_before_references_declared_steps(self) -> "WorkflowStateMachineConfig":
        """
        Ensure every ``hitl_before`` entry references a declared step key.

        This prevents silent misconfiguration where a typo in ``hitl_before``
        would result in a LangGraph interrupt that never fires because the
        node name does not match any step in the graph.

        Raises:
            ValueError: If any ``hitl_before`` entry is not a declared step key.
        """
        if not self.hitl_before:
            return self
        declared_keys = {step.key for step in self.steps}
        unknown = [k for k in self.hitl_before if k not in declared_keys]
        if unknown:
            raise ValueError(
                f"workflow_sm.hitl_before references step key(s) not declared in "
                f"workflow_sm.steps: {unknown}. "
                f"Declared keys: {sorted(declared_keys) if declared_keys else '(none)'}."
            )
        return self

    @model_validator(mode="after")
    def _validate_step_keys_unique(self) -> "WorkflowStateMachineConfig":
        """
        Ensure all step keys within steps are unique.

        Duplicate step keys would cause LangGraph to silently overwrite a node
        registration, resulting in a graph that does not match the configured
        topology.  This check catches duplicates early with an actionable message.

        Raises:
            ValueError: If any step key appears more than once in steps.
        """
        keys = [s.key for s in self.steps]
        dupes = sorted({k for k in keys if keys.count(k) > 1})
        if dupes:
            raise ValueError(
                f"workflow_sm.steps contains duplicate step key(s): {dupes}. "
                f"Each step key must be unique (used as LangGraph node name)."
            )
        return self


class FanoutConfig(BaseModel):
    """Per-pattern configuration for the ``fanout`` execution pattern (v2)."""
    reducer: Literal["concat", "merge_dict"] = Field(
        "concat",
        description=(
            "Strategy used to combine per-agent results: "
            "'concat' appends to a list; 'merge_dict' merges dicts by key."
        ),
    )
    results_field: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$", min_length=1, max_length=64)] = Field(
        "fanout_results",
        description=(
            "Name of the state field that collects per-agent results via the "
            "Annotated[list, operator.add] reducer. Must be a valid Python identifier "
            "(lowercase, underscores). Defaults to 'fanout_results'."
        ),
    )


class OrchestratorConfig(BaseModel):
    """
    Per-pattern configuration for the ``orchestrator`` execution pattern (v2).

    The orchestrator dispatches work to one or more agents and collects their
    outputs. It can operate in two sub-kinds:

    - ``llm``: The supervisor/orchestrator node is an LLM that decides routing
      dynamically (equivalent to the existing LLM-based supervisor).
    - ``rule``: Routing is deterministic, driven by configuration rather than
      an LLM call.
    """
    kind: Literal["llm", "rule"] = Field(
        ...,
        description="Orchestrator sub-kind: 'llm' (dynamic LLM routing) or 'rule' (deterministic).",
    )


class PlannerConfig(BaseModel):
    """Per-pattern configuration for the ``planner`` execution pattern (v2)."""
    max_replans: int = Field(
        2,
        ge=0,
        le=10,
        description=(
            "Maximum number of replan attempts before the planner gives up. "
            "Both precheck failures and validator rejections count against this limit."
        ),
    )
    max_concurrency: int = Field(
        4,
        ge=1,
        description="Maximum number of plan steps executed concurrently by SolverNode.",
    )
    precheck_enabled: bool = Field(
        True,
        description=(
            "Run PlanPrecheckNode (structural DAG validation — no LLM call) "
            "before executing any plan steps."
        ),
    )
    validator_enabled: bool = Field(
        True,
        description="Run ValidatorNode (LLM post-execution coverage check) after SolverNode.",
    )
    composer_enabled: bool = Field(
        True,
        description="Run ComposerNode to stitch solver results into a final answer.",
    )
    llm_model: str = Field(
        "gpt-4o-mini",
        description="LLM model used for planner, validator, and composer nodes.",
    )
    llm_temperature: float = Field(
        0.0,
        ge=0.0,
        le=2.0,
        description="LLM sampling temperature for planner, validator, and composer nodes.",
    )


class StoreSpec(BaseModel):
    """Declarative spec for a store kind that gets a CRUD scaffold.

    Each spec produces a generated module at backend/services/{name}_store.py
    containing a Protocol, in-memory impl, optional BigQuery/Postgres impls,
    and a build_{name}_store(settings) factory.

    Projects extend the InMemory impl as the dev default and swap in a real
    backend via the {NAME}_STORE_BACKEND env var.
    """

    name: SlugStr = Field(
        ...,
        description=(
            "Store name in snake_case (must match ^[a-z][a-z0-9_]*$). "
            "Becomes the file name (`backend/services/{name}_store.py`) "
            "and the env-var prefix (`{NAME}_STORE_BACKEND`)."
        ),
    )
    backends: list[Literal["memory", "bigquery", "postgres"]] = Field(
        default_factory=lambda: ["memory"],
        description=(
            "Which backends the store template emits. 'memory' is always "
            "available (the in-process default). 'bigquery' and 'postgres' "
            "are optional — the generated factory selects on the env var."
        ),
    )
    default: Literal["memory", "bigquery", "postgres"] = Field(
        default="memory",
        description=(
            "Backend selected when the *_STORE_BACKEND env var is unset. "
            "Must be present in `backends`."
        ),
    )

    @model_validator(mode="after")
    def _default_must_be_in_backends(self) -> "StoreSpec":
        if self.default not in self.backends:
            raise ValueError(
                f"StoreSpec(name={self.name!r}).default={self.default!r} "
                f"must be in backends={self.backends!r}"
            )
        return self


# ── Root model ────────────────────────────────────────────────────────────────

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
    enable_settings_module: false    # default; set true to emit backend/config/settings.py

    # v2 fields (optional — omitted in legacy configs):
    entry:
      type: intent_router
    pattern: orchestrator
    orchestrator:
      kind: llm
    """
    # ── v2 top-level fields (all optional; None means legacy/unset) ────────────
    entry: EntryConfig | None = Field(
        None,
        description=(
            "How the graph receives work (v2). "
            "Injected automatically for legacy configs as 'intent_router'."
        ),
    )
    pattern: _PATTERN_LITERALS | None = Field(
        None,
        description=(
            "Execution pattern (v2): react | workflow | fanout | orchestrator | planner. "
            "Injected automatically for legacy configs as 'orchestrator'."
        ),
    )
    react: ReactConfig | None = Field(None, description="Config for pattern='react' (v2).")
    workflow_sm: WorkflowStateMachineConfig | None = Field(
        None,
        description=(
            "Config for pattern='workflow' (v2). The YAML key is 'workflow_sm' (not 'workflow') "
            "to avoid collision with the existing top-level 'workflow: WorkflowConfig' block."
        ),
    )
    fanout: FanoutConfig | None = Field(None, description="Config for pattern='fanout' (v2).")
    orchestrator: OrchestratorConfig | None = Field(
        None, description="Config for pattern='orchestrator' (v2)."
    )
    planner: PlannerConfig | None = Field(None, description="Config for pattern='planner' (v2).")

    # ── existing fields ────────────────────────────────────────────────────────
    metadata: ProjectMetadata
    agents: list[AgentConfig] = Field(..., min_length=1)
    database: DatabaseConfig = Field(default_factory=lambda: DatabaseConfig())  # type: ignore[call-arg]
    workflow: WorkflowConfig = Field(default_factory=lambda: WorkflowConfig())  # type: ignore[call-arg]
    api: APIConfig = Field(default_factory=lambda: APIConfig())  # type: ignore[call-arg]
    observability: ObservabilityConfig = Field(default_factory=lambda: ObservabilityConfig())  # type: ignore[call-arg]
    security: SecurityConfig = Field(default_factory=lambda: SecurityConfig())  # type: ignore[call-arg]
    multi_tenancy: MultiTenancyConfig = Field(default_factory=MultiTenancyConfig)
    ci: CiConfig = Field(default_factory=lambda: CiConfig())  # type: ignore[call-arg]
    development: DevelopmentConfig = Field(default_factory=lambda: DevelopmentConfig())  # type: ignore[call-arg]
    testing: TestingConfig = Field(default_factory=lambda: TestingConfig())  # type: ignore[call-arg]
    enable_provider_registry: bool = Field(
        False,
        description="Generate backend/config/provider_registry.py in the scaffolded project.",
    )
    stores: list[StoreSpec] = Field(
        default_factory=list,
        description=(
            "List of store kinds to scaffold. Each entry produces a "
            "`backend/services/{name}_store.py` module via the store_backend "
            "macro. Empty by default (preserves byte-identity for existing "
            "project.yaml files)."
        ),
    )
    enable_settings_module: bool = Field(
        default=False,
        description=(
            "Emit a typed Pydantic-Settings module at backend/config/settings.py "
            "with SecretStr-typed keys, .env auto-load, and empty-string-rejecting "
            "validators. Off by default to preserve existing scattered "
            "os.environ.get() patterns; opt in for projects adopting the new "
            "convention."
        ),
    )

    # ── backwards-compat validator ─────────────────────────────────────────────

    @model_validator(mode="before")
    @classmethod
    def _inject_v2_defaults_for_legacy_configs(cls, data: Any) -> Any:
        """
        Detect legacy project.yaml shape and rewrite it to the equivalent v2 shape.

        A config is considered *legacy* when ALL of the following hold:
        - No ``entry`` key present
        - No ``pattern`` key present
        - ``workflow.default_intent`` is set (i.e. it is an intent-router style config)
        - At least one agent is declared

        Legacy configs are rewritten to:
            entry.type      = "intent_router"
            pattern         = "orchestrator"
            orchestrator    = {kind: "llm"}

        Additionally, any Tool that is missing a ``kind`` field gets ``kind="mcp"``
        defaulted here so that old tool declarations keep working transparently.

        This validator runs *before* field construction so the injected values
        participate in the normal Pydantic validation pipeline.
        """
        if not isinstance(data, dict):
            return data

        data = dict(data)  # shallow copy — never mutate caller's dict

        # Default missing tool `kind` to "mcp" for every agent's tool list.
        # This handles configs predating v2 tool-kind tagging (TODO-v2-7 risk).
        raw_agents = data.get("agents", [])
        if isinstance(raw_agents, list):
            patched_agents = []
            for agent in raw_agents:
                if isinstance(agent, dict):
                    agent = dict(agent)
                    raw_tools = agent.get("tools", [])
                    if isinstance(raw_tools, list):
                        patched_tools = []
                        for tool in raw_tools:
                            if isinstance(tool, dict) and tool.get("kind") is None:
                                tool = dict(tool)
                                tool["kind"] = "mcp"
                            patched_tools.append(tool)
                        agent["tools"] = patched_tools
                patched_agents.append(agent)
            data["agents"] = patched_agents

        # Only inject v2 entry/pattern/orchestrator when the config is legacy.
        has_entry = "entry" in data
        has_pattern = "pattern" in data

        if has_entry or has_pattern:
            # Already a v2-shaped config — no injection needed.
            return data

        workflow_raw = data.get("workflow", {})
        workflow_dict = workflow_raw if isinstance(workflow_raw, dict) else {}
        has_default_intent = "default_intent" in workflow_dict
        has_agents = bool(data.get("agents"))

        if has_default_intent and has_agents:
            # Classic legacy shape: inject v2 fields.
            data["entry"] = {"type": "intent_router"}
            data["pattern"] = LEGACY_DEFAULT_PATTERN
            data["orchestrator"] = {"kind": "llm"}

        return data

    # ── existing after validators ──────────────────────────────────────────────

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

    @model_validator(mode="after")
    def check_workflow_flags_pattern_compat(self) -> "ProjectConfig":
        """
        Guard workflow.enable_feedback_loop and enable_validation_node against incompatible patterns.

        These flags only make sense in the ``orchestrator`` and ``react`` patterns.
        When a v2 config explicitly sets ``pattern`` to ``workflow``, ``fanout``, or
        ``planner``, enabling them is a misconfiguration that would generate dead code.

        Legacy configs resolve to ``pattern=orchestrator`` via the before-validator
        so they are never affected by this guard.

        Raises:
            ValueError: When an incompatible pattern is set alongside a flag that
                requires orchestrator/react topology.
        """
        if self.pattern in _FLAGS_COMPATIBLE_PATTERNS or self.pattern is None:
            return self
        if self.workflow.enable_feedback_loop:
            raise ValueError(
                f"workflow.enable_feedback_loop is not supported for pattern='{self.pattern}'. "
                "Set enable_feedback_loop=false or switch to pattern='orchestrator' or 'react'."
            )
        if self.workflow.enable_validation_node:
            raise ValueError(
                f"workflow.enable_validation_node is not supported for pattern='{self.pattern}'. "
                "Set enable_validation_node=false or switch to pattern='orchestrator' or 'react'."
            )
        return self

    @model_validator(mode="after")
    def check_workflow_sm_steps_required(self) -> "ProjectConfig":
        """
        Enforce that ``workflow_sm.steps`` has at least one entry when ``pattern='workflow'``.

        A workflow state machine with no steps cannot produce a valid LangGraph graph
        (there are no nodes to wire between START and END). This check fires only
        when the user has explicitly set ``pattern: workflow``; other patterns are
        unaffected.

        Raises:
            ValueError: When ``pattern='workflow'`` and ``workflow_sm.steps`` is empty
                or ``workflow_sm`` is absent.
        """
        if self.pattern != "workflow":
            return self
        if self.workflow_sm is None or len(self.workflow_sm.steps) == 0:
            raise ValueError(
                "workflow_sm.steps must contain at least one step when pattern='workflow'. "
                "Add one or more steps under the 'workflow_sm.steps' key in your project.yaml."
            )
        return self

    @model_validator(mode="after")
    def _validate_agent_keys_unique(self) -> "ProjectConfig":
        """
        Enforce that every agent key is unique within the project.

        Agent keys are used as LangGraph node names; duplicate node names would
        cause silent overwrites during graph compilation, resulting in a graph
        that does not match the configured topology.

        Raises:
            ValueError: If any agent key appears more than once in ``agents``.
        """
        keys = [a.key for a in self.agents]
        dupes = sorted({k for k in keys if keys.count(k) > 1})
        if dupes:
            raise ValueError(
                f"agents contains duplicate key(s): {dupes}. "
                f"Each agent key must be unique (used as LangGraph node name)."
            )
        return self

    @model_validator(mode="after")
    def _validate_store_names_unique(self) -> "ProjectConfig":
        """
        Enforce that every store name is unique within the project.

        Store names are used as the output file name for each generated store
        module (backend/services/{name}_store.py). Duplicate names would cause
        a silent file overwrite when the writer emits the second store.

        Raises:
            ValueError: If any store name appears more than once in stores.
        """
        names = [s.name for s in self.stores]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(
                f"stores contains duplicate name(s): {dupes}. "
                "Each store name must be unique (used as the output file name)."
            )
        return self

    @model_validator(mode="after")
    def _validate_orchestrator_config_matches_pattern(self) -> "ProjectConfig":
        """
        Guard against setting the ``orchestrator`` sub-config on a non-orchestrator pattern.

        ``pattern=None`` is tolerated because the legacy-compat before-validator has
        not yet resolved the pattern for old configs; after the before-validator fires
        for a true legacy config the pattern will be ``"orchestrator"``.  If a user
        explicitly supplies a v2 config with ``orchestrator`` set and a different
        pattern, that is a misconfiguration that this validator rejects.

        Raises:
            ValueError: When ``orchestrator`` is set and ``pattern`` is neither
                ``None`` nor ``"orchestrator"``.
        """
        if self.orchestrator is not None and self.pattern not in (None, "orchestrator"):
            raise ValueError(
                f"orchestrator config is set but pattern='{self.pattern}'. "
                f"Set pattern='orchestrator' or remove the orchestrator sub-config."
            )
        return self

    @model_validator(mode="after")
    def _warn_multi_tenancy_without_jwt(self) -> "ProjectConfig":
        """Warn when multi_tenancy.enabled=True but auth_type != 'jwt'.

        Anonymous tenants without JWT means credential_provider has no user
        context to scope by. This is likely a misconfiguration in production
        (though may be intentional for testing). We warn, never raise.
        """
        if self.multi_tenancy.enabled and self.security.auth_type != "jwt":
            warnings.warn(
                "multi_tenancy.enabled=True with auth_type != 'jwt' means "
                "anonymous tenants — credential_provider has no user context "
                "to scope by. This may be intentional for testing but is rarely "
                "what you want in production.",
                UserWarning,
                stacklevel=2,
            )
        return self
