"""
Jinja2-based template rendering engine.

This module is responsible for rendering Jinja2 templates using the project
configuration as context. It transforms the abstract configuration into concrete
code files that make up the scaffolded project.

Key features:
- Templates are loaded from the package-internal `templates/` directory
  (installed alongside the wheel; accessed via importlib.resources)
- A Jinja2 Environment is built per render call using a ``ChoiceLoader`` that
  first checks ``templates/patterns/{pattern}/`` for per-pattern overrides,
  then falls back to the shared ``templates/`` directory.
- Custom filters are registered: `snake_case`, `pascal_case`, `upper_snake`
- Template context is always a flat dict built from a ProjectConfig instance
- Supports rendering the entire project or individual components

The TemplateRenderer class is the main entry point for template rendering operations.
It provides methods to render all templates for a project or just specific components
like a single agent.
"""
from __future__ import annotations

import importlib.resources
from pathlib import Path
from typing import Callable, Union

from jinja2 import (
    ChoiceLoader,
    Environment,
    FileSystemLoader,
    select_autoescape,
    StrictUndefined,
    TemplateNotFound,
    UndefinedError,
)
from rich.console import Console

from ..schema.models import ProjectConfig, AgentConfig, LEGACY_DEFAULT_PATTERN, is_valid_pattern
from . import resolve_pattern
from .filters import snake_case, pascal_case, upper_snake

console = Console()

# Resolved once at import time — the on-disk root of the agentforge/templates/ tree.
# Using importlib.resources ensures this works both in editable installs and from a
# built wheel (where the package is extracted to site-packages).
_TEMPLATES_ROOT: Path = Path(str(importlib.resources.files("agentforge"))) / "templates"

# Type alias for entries in STATIC_TEMPLATE_MAP.  Four supported shapes:
#   (str, str)                              — always renders
#   (str, str, Callable[[ProjectConfig], bool])  — renders only if predicate is true
#   (Callable[[ProjectConfig], str], str)   — template name resolved at render time (swap)
#   (Callable[[ProjectConfig], str], str, Callable[[ProjectConfig], bool])  — swap + predicate
TemplateMapEntry = Union[
    tuple[str, str],
    tuple[str, str, Callable[[ProjectConfig], bool]],
    tuple[Callable[[ProjectConfig], str], str],
    tuple[Callable[[ProjectConfig], str], str, Callable[[ProjectConfig], bool]],
]


def _resolve_logging_template(config: ProjectConfig) -> str:
    """Swap between the stdlib and structlog logging templates based on flag."""
    if config.observability.structured_logging:
        return "logging_structlog.py.j2"
    return "logging.py.j2"


def _benchmarks_enabled(c: ProjectConfig) -> bool:
    """True when DeepEval benchmarks are fully opted in."""
    return c.testing.enable_benchmarks and c.testing.eval_framework == "deepeval"


def _has_mcp(c: ProjectConfig) -> bool:
    """True when any agent tool is of kind 'mcp' with an mcp_resource reference."""
    return any(
        tool.kind == "mcp" and getattr(tool, "mcp_resource", None)
        for agent in c.agents
        for tool in agent.tools
    )


def _has_http_tool(c: ProjectConfig) -> bool:
    """True when any agent tool is of kind 'http'."""
    return any(
        tool.kind == "http"
        for agent in c.agents
        for tool in agent.tools
    )


def _has_agent_tool(c: ProjectConfig) -> bool:
    """True when any agent tool is of kind 'agent'."""
    return any(
        tool.kind == "agent"
        for agent in c.agents
        for tool in agent.tools
    )


def _has_any_tool(c: ProjectConfig) -> bool:
    """True when the project has at least one HTTP or agent tool.

    MCP-only projects do not get a tool_registry.py to preserve byte-identity
    with legacy configs (the mcp_client.py already serves MCP tool loading).
    When HTTP or agent tools are present, tool_registry.py is generated and
    aggregates ALL tool kinds (including MCP) into one unified callable dict.
    """
    return _has_http_tool(c) or _has_agent_tool(c)


def _is_react(c: ProjectConfig) -> bool:
    """True when the project uses the react execution pattern."""
    return resolve_pattern(c) == "react"


def _is_fanout(c: ProjectConfig) -> bool:
    """True when the project uses the fanout execution pattern."""
    return resolve_pattern(c) == "fanout"


def _is_workflow(c: ProjectConfig) -> bool:
    """True when the project uses the workflow (state machine) execution pattern."""
    return resolve_pattern(c) == "workflow"


def _is_planner(c: ProjectConfig) -> bool:
    """True when the project uses the planner (plan-and-execute) execution pattern."""
    return resolve_pattern(c) == "planner"


def _is_planner_precheck(c: ProjectConfig) -> bool:
    """True when planner pattern is active AND precheck_enabled=True."""
    if not _is_planner(c):
        return False
    cfg = c.planner
    return cfg.precheck_enabled if cfg is not None else True


def _is_planner_validator(c: ProjectConfig) -> bool:
    """True when planner pattern is active AND validator_enabled=True."""
    if not _is_planner(c):
        return False
    cfg = c.planner
    return cfg.validator_enabled if cfg is not None else True


def _is_planner_composer(c: ProjectConfig) -> bool:
    """True when planner pattern is active AND composer_enabled=True."""
    if not _is_planner(c):
        return False
    cfg = c.planner
    return cfg.composer_enabled if cfg is not None else True


def _is_passthrough_entry(c: ProjectConfig) -> bool:
    """True when the project uses the passthrough entry type.

    The passthrough entry expects the caller to supply ``intent`` in the request
    body while the LLM extracts only the structured ``inputs`` from the query text.
    """
    return c.entry is not None and c.entry.type == "passthrough"


def _is_direct_entry(c: ProjectConfig) -> bool:
    """True when the project uses the direct entry type.

    The direct entry accepts typed ``{intent, inputs}`` directly from the caller
    with no LLM parsing at the entry layer.
    """
    return c.entry is not None and c.entry.type == "direct"


def _is_intent_router_entry(c: ProjectConfig) -> bool:
    """True when the project uses the intent_router entry (LLM classifies intent).

    Legacy configs with no explicit ``entry`` block resolve to ``intent_router``
    via the before-validator shim, so this also returns True for those.
    """
    return c.entry is None or c.entry.type == "intent_router"


def _has_stores(c: ProjectConfig) -> bool:
    """True when the project declares at least one store (TODO-L12)."""
    return bool(c.stores)


def _has_bigquery_store(c: ProjectConfig) -> bool:
    """True if any declared StoreSpec lists 'bigquery' in its backends."""
    return any("bigquery" in store.backends for store in c.stores)


def _has_postgres_store(c: ProjectConfig) -> bool:
    """True if any declared StoreSpec lists 'postgres' in its backends."""
    return any("postgres" in store.backends for store in c.stores)


def _make_env(pattern: str) -> Environment:
    """
    Build a Jinja2 Environment with a ``ChoiceLoader`` for the given pattern.

    Loader precedence (first match wins):
    1. ``templates/patterns/{pattern}/`` — per-pattern overrides.
    2. ``templates/`` — shared base templates (existing behaviour).

    The pattern directory is allowed to be absent or empty; ``FileSystemLoader``
    handles missing directories gracefully by raising ``TemplateNotFound`` only
    when a template is actually looked up there and not found.

    Args:
        pattern: The execution pattern name (e.g. ``"orchestrator"``).

    Returns:
        A configured ``Environment`` instance with custom filters registered.

    Raises:
        ValueError: If *pattern* is not a member of ``_PATTERN_LITERALS``.
    """
    if not is_valid_pattern(pattern):
        raise ValueError(
            f"Unknown pattern {pattern!r}. "
            f"Must be one of the _PATTERN_LITERALS defined in agentforge.schema.models."
        )
    pattern_dir = _TEMPLATES_ROOT / "patterns" / pattern
    env = Environment(
        loader=ChoiceLoader([
            FileSystemLoader(str(pattern_dir)),
            FileSystemLoader(str(_TEMPLATES_ROOT)),
        ]),
        autoescape=select_autoescape([]),   # Python code — no HTML escaping
        undefined=StrictUndefined,          # fail fast on missing variables
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["snake_case"]  = snake_case
    env.filters["pascal_case"] = pascal_case
    env.filters["upper_snake"] = upper_snake
    return env


class TemplateRenderer:
    """
    Renders Jinja2 templates using ProjectConfig as the render context.

    This class is responsible for transforming the project configuration into
    actual code files by rendering Jinja2 templates. It maintains a single
    Jinja2 Environment instance with custom filters and configuration.

    The renderer handles both static templates (rendered once per project)
    and dynamic templates (rendered for each agent).

    Template resolution uses a ``ChoiceLoader`` that prefers per-pattern
    overrides under ``templates/patterns/{pattern}/`` and falls back to the
    shared ``templates/`` directory.  The pattern is resolved from
    ``config.pattern`` via ``resolve_pattern(config)``.

    The ``_env`` property exposes the default (``orchestrator``) environment
    for callers that need direct template access outside of ``render_all``.
    Since the orchestrator pattern directory is currently empty, ``_env``
    resolves all templates from the shared ``templates/`` directory — identical
    to the previous ``PackageLoader`` behaviour.
    """

    def __init__(self) -> None:
        # No Jinja env is built at construction time.  A per-pattern env is
        # created on each render call via _get_env() so the correct overlay
        # directory is always selected.  The _env property exposes the default
        # orchestrator env for callers that need direct template access.
        pass

    @property
    def _env(self) -> Environment:
        """
        Default Jinja2 Environment using the ``orchestrator`` pattern overlay.

        This property exists for backward compatibility with tests and internal
        helpers that access the environment directly (e.g. to render a single
        template without going through ``render_all``).

        Since the ``orchestrator`` pattern directory is currently empty, all
        template lookups fall through to the shared ``templates/`` directory —
        producing the same result as the previous ``PackageLoader`` environment.
        """
        return _make_env(LEGACY_DEFAULT_PATTERN)

    def _get_env(self, config: ProjectConfig) -> Environment:
        """Return a Jinja2 Environment configured for the config's pattern."""
        return _make_env(resolve_pattern(config))

    # ── Public API ────────────────────────────────────────────────────────────

    def render_all(self, config: ProjectConfig) -> list[tuple[Path, str]]:
        """
        Render every template for the given project configuration.

        This method renders all templates needed for a complete project scaffold,
        including both static templates (rendered once per project) and dynamic
        templates (rendered for each agent and each declared store).

        Args:
            config: The validated ProjectConfig containing all project settings

        Returns:
            A list of (relative_path, rendered_content) tuples in the order they
            should be written to disk. The relative paths are from the project root.

        Example:
            ```python
            renderer = TemplateRenderer()
            files = renderer.render_all(project_config)
            for path, content in files:
                # Write content to path
            ```
        """
        env = self._get_env(config)
        ctx = self._build_context(config)
        results: list[tuple[Path, str]] = []

        # Static (per-project) templates
        for entry in STATIC_TEMPLATE_MAP:
            # Resolve template name: literal string or callable that returns one.
            tmpl_name = entry[0](config) if callable(entry[0]) else entry[0]
            rel_path = entry[1]
            # Evaluate optional predicate (3-tuple); skip this entry if it returns False.
            predicate = entry[2] if len(entry) == 3 else None
            if predicate is not None and not predicate(config):
                continue
            content = self._render(env, tmpl_name, ctx)
            results.append((Path(rel_path), content))

        # Dynamic (per-agent) templates
        for agent in config.agents:
            agent_ctx = {**ctx, "agent": agent.model_dump()}
            content = self._render(env, "agent.py.j2", agent_ctx)
            results.append((Path(f"backend/agents/{agent.key}_agent.py"), content))

        # Dynamic (per-store) templates — TODO-L12
        # One output file per StoreSpec: backend/services/{name}_store.py
        # Empty stores list → loop body never executes → no new files emitted.
        for store in config.stores:
            store_ctx = {**ctx, "store": store.model_dump()}
            content = self._render(env, "store_backend.py.j2", store_ctx)
            results.append((Path(f"backend/services/{store.name}_store.py"), content))

        return results

    def render_agent(
        self, agent: AgentConfig, config: ProjectConfig
    ) -> list[tuple[Path, str]]:
        """
        Render only the files needed for a single new agent.

        This method is used when adding a new agent to an existing project.
        It renders the agent-specific file and updates the registry file
        to include the new agent.

        Args:
            agent: The AgentConfig for the new agent to render
            config: The complete ProjectConfig for context

        Returns:
            A list of (relative_path, rendered_content) tuples for the
            agent file and updated registry file
        """
        env = self._get_env(config)
        ctx = self._build_context(config)
        agent_ctx = {**ctx, "agent": agent.model_dump()}

        results = []
        # The agent module itself
        content = self._render(env, "agent.py.j2", agent_ctx)
        results.append((Path(f"backend/agents/{agent.key}_agent.py"), content))
        # Re-render registry.py to include the new agent
        content = self._render(env, "registry.py.j2", ctx)
        results.append((Path("backend/agents/registry.py"), content))
        return results

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _render(self, env: Environment, template_name: str, ctx: dict) -> str:
        """
        Render a single template with the given context.

        Args:
            env: The Jinja2 Environment to use (already configured for the pattern).
            template_name: Name of the template file (e.g., "agent.py.j2")
            ctx: Context dictionary with variables for the template

        Returns:
            The rendered template content as a string

        Raises:
            TemplateNotFound: If the template doesn't exist in either the
                pattern overlay or the shared templates directory.
            UndefinedError: If the template references undefined variables
        """
        if not self._template_exists(env, template_name):
            console.print(f"[red]✗[/red] Template not found: {template_name}")
            raise TemplateNotFound(template_name)

        try:
            tmpl = env.get_template(template_name)
            return tmpl.render(**ctx)
        except UndefinedError as e:
            console.print(f"[red]✗[/red] Template rendering error: {str(e)}")
            console.print("[yellow]![/yellow] Missing variable in template. Check your project configuration.")
            raise
        except Exception as e:
            console.print(f"[red]✗[/red] Unexpected error rendering template: {str(e)}")
            raise

    def _template_exists(self, env: Environment, template_name: str) -> bool:
        """
        Check if a template exists in the loader chain (pattern overlay or shared).

        Args:
            env: The Jinja2 Environment to query.
            template_name: Name of the template file to check

        Returns:
            True if the template exists, False otherwise
        """
        try:
            env.get_template(template_name)
            return True
        except TemplateNotFound:
            return False

    @staticmethod
    def _build_context(config: ProjectConfig) -> dict:
        """
        Flatten ProjectConfig into a Jinja2 context dictionary.

        This method converts the hierarchical Pydantic model into a flat
        dictionary that can be used as a context for Jinja2 templates.
        It serializes all nested models to plain dicts/lists and adds
        convenience aliases for commonly used values to simplify template code.

        Args:
            config: The ProjectConfig to convert to a template context

        Returns:
            A dictionary with all configuration values and convenience aliases
            ready to be used in Jinja2 templates

        Note:
            The returned dictionary includes both the full serialized config
            and shortcut aliases for frequently accessed values to make
            templates more readable.
        """
        data = config.model_dump(mode="python")
        # enable_auth is a property (not a Pydantic field), so inject it explicitly
        # into both the flat context and the nested security sub-dict.
        data["security"]["enable_auth"] = config.security.enable_auth
        # Convenience aliases used heavily in templates
        # Metadata aliases
        data["project_name"]                = config.metadata.name
        data["description"]                 = config.metadata.description
        data["python_version"]              = config.metadata.python_version
        data["author"]                      = config.metadata.author
        # Schema field is `email`; exposed as `author_email` to match the TOML authors table key.
        data["author_email"]                = config.metadata.email
        data["agents_list"]                 = [a.model_dump() for a in config.agents]
        data["agent_keys"]                  = [a.key for a in config.agents]
        data["valid_intents"]               = [a.key for a in config.agents]
        # Workflow aliases
        data["default_intent"]              = config.workflow.default_intent
        data["enable_feedback_loop"]        = config.workflow.enable_feedback_loop
        data["enable_validation_node"]      = config.workflow.enable_validation_node
        data["router_llm_model"]            = config.workflow.router_llm_model.value
        data["router_llm_provider"]         = config.workflow.router_llm_provider
        data["max_feedback_attempts"]       = config.workflow.max_feedback_attempts
        data["workflow_enable_checkpointing"] = config.workflow.enable_checkpointing
        # Observability aliases
        data["enable_tracing"]              = config.observability.enable_tracing
        data["tracing_provider"]            = config.observability.tracing_provider
        data["context_fields"]              = config.observability.context_fields
        data["log_rotation_bytes"]          = config.observability.log_rotation_bytes
        data["log_backup_count"]            = config.observability.log_backup_count
        data["structured_logging"]           = config.observability.structured_logging
        # Security aliases — enable_auth is a property so read from model directly
        data["enable_auth"]                 = config.security.enable_auth
        data["api_key_env_var"]             = config.security.api_key_env_var
        data["enable_ip_pseudonymization"]  = config.security.enable_ip_pseudonymization
        # JWT-specific aliases (None when auth_type != "jwt")
        data["auth_type"]                   = config.security.auth_type
        data["jwt_algorithm"]               = config.security.jwt_algorithm
        data["jwt_issuer"]                  = config.security.jwt_issuer
        data["jwt_audience"]                = config.security.jwt_audience
        data["jwks_url"]                    = config.security.jwks_url
        # API aliases
        data["cors_origins"]                = [str(o) for o in config.api.cors.origins]
        data["query_max_length"]            = config.api.query_max_length
        data["allow_credentials"]           = config.api.cors.allow_credentials
        # Database aliases
        data["db_backend"]                  = config.database.backend.value
        data["db_tables"]                   = config.database.tables
        data["db_connection_env_var"]       = config.database.connection_env_var
        data["db_pool_size"]                = config.database.pool_size
        # Database migration aliases
        data["db_use_alembic"]               = config.database.use_alembic
        # CI aliases — prefixed with ci_ to avoid shadowing metadata.python_version
        data["ci_provider"]                 = config.ci.provider
        data["ci_python_version"]           = config.ci.python_version
        data["ci_installer"]                = config.ci.installer
        # Development tooling aliases
        data["dev_pre_commit"]              = config.development.pre_commit
        # Testing / benchmark aliases
        data["testing_enable_benchmarks"]   = config.testing.enable_benchmarks
        data["testing_eval_framework"]      = config.testing.eval_framework
        # Top-level feature flags
        data["enable_provider_registry"]    = config.enable_provider_registry
        # Store specs alias — TODO-L12
        # Serialised list of StoreSpec dicts; fed to store_backend.py.j2 by the
        # dynamic per-store loop. Empty by default (preserves byte-identity for all
        # existing configs).
        data["stores"]                      = [s.model_dump() for s in config.stores]
        # ReAct pattern aliases — expose ReactConfig fields to templates so no
        # numeric or string literals need to be hardcoded inside the .j2 files.
        # These are always populated (ReactConfig has defaults), but are only
        # *used* by templates under patterns/react/.
        _react = config.react
        data["react_max_steps"]    = _react.max_steps    if _react is not None else 12
        data["react_tool_choice"]  = _react.tool_choice  if _react is not None else "auto"
        data["react_temperature"]  = _react.temperature  if _react is not None else 0.0
        # Fanout pattern aliases — expose FanoutConfig fields to templates so no
        # string literals need to be hardcoded inside the .j2 files.
        # These are always populated (FanoutConfig has defaults), but are only
        # *used* by templates under patterns/fanout/.
        _fanout = config.fanout
        data["fanout_reducer"]       = _fanout.reducer       if _fanout is not None else "concat"
        data["fanout_results_field"] = _fanout.results_field if _fanout is not None else "fanout_results"
        # Workflow (state machine) pattern aliases — expose WorkflowStateMachineConfig
        # fields to templates so no step keys or hitl values are hardcoded in the .j2
        # files.  These are always populated (with empty defaults), but are only *used*
        # by templates under patterns/workflow/.
        _wfsm = config.workflow_sm
        data["workflow_steps"] = (
            [{"key": s.key, "description": s.description} for s in _wfsm.steps]
            if _wfsm is not None else []
        )
        data["workflow_hitl_before"] = _wfsm.hitl_before if _wfsm is not None else []
        # Planner pattern aliases — expose PlannerConfig fields to templates so no
        # numeric literals or boolean literals are hardcoded in the .j2 files.
        # These are always populated (with schema defaults), but are only *used*
        # by templates under patterns/planner/.
        _planner = config.planner
        data["planner_max_replans"]      = _planner.max_replans      if _planner is not None else 2
        data["planner_max_concurrency"]  = _planner.max_concurrency  if _planner is not None else 4
        data["planner_precheck_enabled"] = _planner.precheck_enabled if _planner is not None else True
        data["planner_validator_enabled"]= _planner.validator_enabled if _planner is not None else True
        data["planner_composer_enabled"] = _planner.composer_enabled  if _planner is not None else True
        data["planner_llm_model"]        = _planner.llm_model        if _planner is not None else "gpt-4o-mini"
        data["planner_llm_temperature"]  = _planner.llm_temperature  if _planner is not None else 0.0
        # Tool names from the project's declared agent tools — used by planner templates
        # to enumerate the tool registry without hardcoding names.
        data["planner_tool_names"] = [
            tool.name
            for agent in config.agents
            for tool in agent.tools
        ]
        # Computed flag: true when any agent tool is kind='mcp' with an mcp_resource.
        # Used by mcp_client.py.j2 predicate and pyproject.toml.j2 dependency block.
        data["has_mcp"] = any(
            tool.kind == "mcp" and getattr(tool, "mcp_resource", None)
            for agent in config.agents
            for tool in agent.tools
        )
        # Computed flags for the new HTTP and agent tool kinds (TODO-v2-7).
        # Used to gate rendering of http_tool.py, agent_tool.py, and tool_registry.py.
        data["has_http_tool"] = any(
            tool.kind == "http"
            for agent in config.agents
            for tool in agent.tools
        )
        data["has_agent_tool"] = any(
            tool.kind == "agent"
            for agent in config.agents
            for tool in agent.tools
        )
        data["has_any_tool"] = _has_http_tool(config) or _has_agent_tool(config)
        # Computed flag: true when any StoreSpec has 'bigquery' in its backends.
        # Used to gate bigquery_rest_client.py.j2 in STATIC_TEMPLATE_MAP and the
        # conditional google-auth pin in requirements.txt.j2.
        data["has_bigquery_store"] = _has_bigquery_store(config)
        data["has_postgres_store"] = _has_postgres_store(config)
        # Typed tool lists — passed to http_tool.py.j2, agent_tool.py.j2, and
        # tool_registry.py.j2 so that templates iterate over only their kind.
        # Use mode="json" so AnyHttpUrl (and other Pydantic types) are serialized
        # as plain Python strings — safe for Jinja2 | tojson filter.
        data["http_tools"] = [
            tool.model_dump(mode="json")
            for agent in config.agents
            for tool in agent.tools
            if tool.kind == "http"
        ]
        data["agent_tools"] = [
            tool.model_dump(mode="json")
            for agent in config.agents
            for tool in agent.tools
            if tool.kind == "agent"
        ]
        data["all_tools"] = [
            tool.model_dump(mode="json")
            for agent in config.agents
            for tool in agent.tools
        ]
        # Entry type aliases — expose EntryConfig fields to templates so the
        # entry_type branch in main.py.j2 and overlay templates never hardcode strings.
        # ``entry_type`` is always present (the before-validator guarantees it for
        # any config that passes validation); ``entry_screen_context_fields`` may be None.
        _entry = config.entry
        data["entry_type"] = _entry.type if _entry is not None else "intent_router"
        data["entry_screen_context_fields"] = (
            _entry.screen_context_fields if _entry is not None else None
        )
        return data


# ── Template → output file mapping (static, one-per-project templates) ───────
# Each entry is a TemplateMapEntry (see type alias above). Supported shapes:
#   (str, str)                          — always renders
#   (str, str, predicate)               — renders only when predicate(config) is True
#   (resolver, str)                     — template name resolved via resolver(config) at render time
#   (resolver, str, predicate)          — combined swap + conditional
STATIC_TEMPLATE_MAP: list[TemplateMapEntry] = [
    # ── Package markers (__init__.py) ─────────────────────────────────────────
    # Required so that Python treats each directory as a regular package,
    # enabling both absolute imports (with backend/ on sys.path) and relative
    # imports (e.g. `from ..state import AgentState`).
    ("__init__.py.j2",                "backend/__init__.py"),
    ("agents_init.py.j2",             "backend/agents/__init__.py"),
    ("__init__.py.j2",                "backend/graph/__init__.py"),
    ("__init__.py.j2",                "backend/graph/nodes/__init__.py"),
    ("__init__.py.j2",                "backend/observability/__init__.py"),
    ("__init__.py.j2",                "backend/middleware/__init__.py"),
    ("__init__.py.j2",                "backend/security/__init__.py",
     lambda c: c.security.auth_type != "jwt"),
    ("security/auth_init.py.j2",      "backend/security/__init__.py",
     lambda c: c.security.auth_type == "jwt"),
    ("__init__.py.j2",                "backend/config/__init__.py",
     lambda c: c.enable_provider_registry or c.workflow.enable_checkpointing),
    ("__init__.py.j2",                "backend/services/__init__.py",
     lambda c: _has_mcp(c) or _has_any_tool(c) or _has_stores(c)),
    ("__init__.py.j2",                "backend/tests/__init__.py",
     lambda c: c.observability.structured_logging),
    # ── Static (per-project) templates ────────────────────────────────────────
    ("base_agent.py.j2",            "backend/agents/base_agent.py"),
    ("registry.py.j2",              "backend/agents/registry.py"),
    ("state.py.j2",                 "backend/graph/state.py"),
    ("workflow.py.j2",              "backend/graph/workflow.py"),
    ("query_router_node.py.j2",     "backend/graph/nodes/query_router_node.py", _is_intent_router_entry),
    ("supervisor_node.py.j2",       "backend/graph/nodes/supervisor_node.py"),
    ("answer_node.py.j2",           "backend/graph/nodes/answer_node.py"),
    ("validation_node.py.j2",       "backend/graph/nodes/validation_node.py"),
    ("feedback_node.py.j2",         "backend/graph/nodes/feedback_node.py"),
    ("mcp_server.py.j2",            "backend/mcp_server.py"),
    ("main.py.j2",                  "backend/main.py"),
    (_resolve_logging_template,     "backend/observability/logging.py"),
    ("tracing.py.j2",               "backend/observability/tracing.py"),
    ("auth.py.j2",                  "backend/security/auth.py",
     lambda c: c.security.auth_type == "api_key"),
    ("sanitizer.py.j2",             "backend/security/sanitizer.py"),
    ("logging_middleware.py.j2",    "backend/middleware/logging_middleware.py"),
    ("test_structlog_setup.py.j2",   "backend/tests/test_structlog_setup.py",
     lambda c: c.observability.structured_logging),
    ("requirements.txt.j2",         "requirements.txt"),
    ("env.j2",                      ".env.example"),
    ("README.md.j2",                "README.md"),
    ("gitignore.j2",                ".gitignore"),
    # ── Secret-scanning scaffold ──────────────────────────────────────────────
    # Always rendered (unconditional 2-tuple) — every project gets a gitleaks
    # config and a GitHub secret-scanning ignore list regardless of feature flags.
    (".gitleaks.toml.j2",           ".gitleaks.toml"),
    (".secretscanignore.j2",        ".secretscanignore"),
    # ── Makefile scaffold ─────────────────────────────────────────────────────────
    ("Makefile.j2",                  "Makefile"),
    ("provider_registry.py.j2",     "backend/config/provider_registry.py",
     lambda c: c.enable_provider_registry),
    ("providers.yaml.j2",           "backend/config/providers.yaml",
     lambda c: c.enable_provider_registry),
    # ── Alembic migration scaffold ────────────────────────────────────────────
    ("alembic.ini.j2",               "alembic.ini",
     lambda c: c.database.use_alembic),
    ("alembic/env.py.j2",            "backend/migrations/env.py",
     lambda c: c.database.use_alembic),
    ("alembic/script.py.mako.j2",    "backend/migrations/script.py.mako",
     lambda c: c.database.use_alembic),
    # ── GitHub Actions CI scaffold ────────────────────────────────────────────
    ("ci/github_ci.yml.j2",          ".github/workflows/ci.yml",
     lambda c: c.ci.provider == "github"),
    # ── Pre-commit hooks scaffold ─────────────────────────────────────────────
    ("precommit_config.yaml.j2",     ".pre-commit-config.yaml",
     lambda c: c.development.pre_commit),
    # ── Type-checking config scaffold ────────────────────────────────────────
    ("pyrightconfig.json.j2",         "pyrightconfig.json",
     lambda c: c.development.type_checking == "pyright"),
    # ── MCP client scaffold ───────────────────────────────────────────────────
    ("mcp_client.py.j2",             "backend/services/mcp_client.py",
     _has_mcp),
    # ── HTTP tool scaffold (TODO-v2-7) ────────────────────────────────────────
    # Generated only when at least one agent tool has kind="http".
    # Emits an httpx-based async callable per declared HTTP tool.
    ("tools/http_tool.py.j2",        "backend/services/http_tool.py",
     _has_http_tool),
    # ── Agent tool scaffold (TODO-v2-7) ──────────────────────────────────────
    # Generated only when at least one agent tool has kind="agent".
    # Emits an httpx-based async callable per declared agent tool (JWT auth).
    ("tools/agent_tool.py.j2",       "backend/services/agent_tool.py",
     _has_agent_tool),
    # ── Tool registry scaffold (TODO-v2-7) ───────────────────────────────────
    # Generated when any tool of any kind is declared.
    # Central dict keyed by tool name used by all downstream nodes.
    ("tools/tool_registry.py.j2",    "backend/services/tool_registry.py",
     _has_any_tool),
    # ── BigQuery REST client scaffold ─────────────────────────────────────────
    # Emitted only when at least one StoreSpec has "bigquery" in its backends.
    # Uses google-auth + httpx (NOT google-cloud-bigquery) for a lean dep tree.
    ("services/bigquery_rest_client.py.j2", "backend/services/bigquery_rest_client.py",
     _has_bigquery_store),
    # ── ReAct pattern: compiled graph-app factory ────────────────────────────
    # Rendered only when pattern == "react".  The template lives under
    # patterns/react/ and is picked up by the ChoiceLoader automatically; it
    # is listed here so the ScaffoldWriter knows to emit the output file.
    ("graph_agent.py.j2",            "backend/graph/graph_agent.py",
     _is_react),
    # ── Fanout pattern: orchestrator and reducer nodes ────────────────────────
    # Rendered only when pattern == "fanout".  Templates live under
    # patterns/fanout/ and are picked up by the ChoiceLoader automatically.
    ("orchestrator_node.py.j2",      "backend/graph/nodes/orchestrator_node.py",
     _is_fanout),
    ("reducer_node.py.j2",           "backend/graph/nodes/reducer_node.py",
     _is_fanout),
    # ── Workflow (state machine) pattern: human-review resume node ────────────
    # Rendered only when pattern == "workflow".  The template lives under
    # patterns/workflow/ and is picked up by the ChoiceLoader automatically.
    # The main workflow.py is already in the static list above as "workflow.py.j2";
    # the ChoiceLoader selects the pattern-specific overlay automatically.
    ("human_review_node.py.j2",      "backend/graph/nodes/human_review_node.py",
     _is_workflow),
    # ── LangGraph PostgresSaver checkpointing scaffold ────────────────────────
    ("graph/postgres_with_saver.py.j2",  "backend/graph/checkpointer.py",
     lambda c: c.workflow.enable_checkpointing),
    ("config/memory_settings.py.j2",     "backend/config/memory_settings.py",
     lambda c: c.workflow.enable_checkpointing),
    # ── JWT auth scaffold ─────────────────────────────────────────────────────
    ("security/jwt.py.j2",           "backend/security/jwt.py",
     lambda c: c.security.auth_type == "jwt"),
    ("security/dtos.py.j2",          "backend/security/dtos.py",
     lambda c: c.security.auth_type == "jwt"),
    ("security/jwt_settings.py.j2",  "backend/security/jwt_settings.py",
     lambda c: c.security.auth_type == "jwt"),
    ("middleware/permission_gate.py.j2", "backend/middleware/permission_gate.py",
     lambda c: c.security.auth_type == "jwt"),
    # ── Prompt secret scanner scaffold ───────────────────────────────────────
    ("security/prompt_secret_scanner.py.j2", "backend/security/prompt_secret_scanner.py",
     lambda c: c.security.enable_prompt_secret_scan),
    # ── DeepEval benchmark scaffold ───────────────────────────────────────────
    # All entries gated on enable_benchmarks=True AND eval_framework="deepeval".
    # Output under backend/tests/benchmarks/ — mirrors the test layout expected
    # by pytest when run from the project root.
    ("__init__.py.j2",                         "backend/tests/__init__.py",
     _benchmarks_enabled),
    ("benchmarks/__init__.py.j2",              "backend/tests/benchmarks/__init__.py",
     _benchmarks_enabled),
    ("benchmarks/conftest.py.j2",              "backend/tests/benchmarks/conftest.py",
     _benchmarks_enabled),
    ("benchmarks/datasets.py.j2",              "backend/tests/benchmarks/datasets.py",
     _benchmarks_enabled),
    ("benchmarks/generators.py.j2",            "backend/tests/benchmarks/generators.py",
     _benchmarks_enabled),
    ("benchmarks/report_plugin.py.j2",         "backend/tests/benchmarks/report_plugin.py",
     _benchmarks_enabled),
    ("benchmarks/runner.py.j2",                "backend/tests/benchmarks/runner.py",
     _benchmarks_enabled),
    ("benchmarks/test_graph_agent.py.j2",      "backend/tests/benchmarks/test_graph_agent.py",
     _benchmarks_enabled),
    ("benchmarks/trigger_command.py.j2",       "backend/tests/benchmarks/trigger_command.py",
     _benchmarks_enabled),
    ("benchmarks/utils.py.j2",                 "backend/tests/benchmarks/utils.py",
     _benchmarks_enabled),
    ("benchmarks/base_mcp_mocks.json.j2",      "backend/tests/benchmarks/base_mcp_mocks.json",
     _benchmarks_enabled),
    # ── Planner pattern: plan-and-execute nodes ───────────────────────────────
    # All planner nodes are gated on pattern == "planner".
    # Individual nodes are further gated on their respective enabled flags.
    # The workflow.py overlay is picked up automatically by ChoiceLoader;
    # it is listed here so ScaffoldWriter emits it under the correct path.
    # _precheck.py is always emitted when planner is active (it's a shared helper
    # imported by plan_precheck_node.py; even when precheck_enabled=False the
    # plan_precheck_node.py is not emitted, so _precheck.py is also suppressed).
    ("plan_and_run_node.py.j2",      "backend/graph/nodes/plan_and_run_node.py",
     _is_planner),
    ("solver_node.py.j2",            "backend/graph/nodes/solver_node.py",
     _is_planner),
    ("_package_init.py.j2",          "backend/graph/planner/__init__.py",
     _is_planner_precheck),
    ("_precheck.py.j2",              "backend/graph/planner/_precheck.py",
     _is_planner_precheck),
    ("plan_precheck_node.py.j2",     "backend/graph/nodes/plan_precheck_node.py",
     _is_planner_precheck),
    ("validator_node.py.j2",         "backend/graph/nodes/validator_node.py",
     _is_planner_validator),
    ("composer_node.py.j2",          "backend/graph/nodes/composer_node.py",
     _is_planner_composer),
    # ── Entry type overlays ───────────────────────────────────────────────────
    # passthrough entry: LLM extracts structured inputs from the query text;
    # intent is already supplied by the caller in the request body.
    # Template lives under patterns/_entry/ and is referenced by its full path
    # relative to _TEMPLATES_ROOT so the ChoiceLoader finds it via the shared
    # FileSystemLoader (not a per-pattern overlay directory).
    ("patterns/_entry/passthrough_node.py.j2",
     "backend/graph/nodes/passthrough_node.py",
     _is_passthrough_entry),
    # direct entry: caller supplies typed {intent, inputs}; no LLM at entry.
    # The generated module contains the DirectEntryRequest Pydantic model imported
    # by backend/main.py when entry.type == "direct".
    ("patterns/_entry/direct_entry.py.j2",
     "backend/graph/direct_entry.py",
     _is_direct_entry),
]
