"""
Jinja2-based template rendering engine.

This module is responsible for rendering Jinja2 templates using the project
configuration as context. It transforms the abstract configuration into concrete
code files that make up the scaffolded project.

Key features:
- Templates are loaded from the package-internal `templates/` directory
  (installed alongside the wheel; accessed via importlib.resources)
- A single Jinja2 Environment is constructed once; all renders share it
- Custom filters are registered: `snake_case`, `pascal_case`, `upper_snake`
- Template context is always a flat dict built from a ProjectConfig instance
- Supports rendering the entire project or individual components

The TemplateRenderer class is the main entry point for template rendering operations.
It provides methods to render all templates for a project or just specific components
like a single agent.
"""
from __future__ import annotations

import importlib.resources
import os
from pathlib import Path
from typing import Callable, Iterator, Optional, Union

from jinja2 import (
    Environment,
    PackageLoader,
    select_autoescape,
    StrictUndefined,
    TemplateNotFound,
    UndefinedError
)
from rich.console import Console

from ..schema.models import ProjectConfig, AgentConfig
from .filters import snake_case, pascal_case, upper_snake

console = Console()

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


class TemplateRenderer:
    """
    Renders Jinja2 templates using ProjectConfig as the render context.

    This class is responsible for transforming the project configuration into
    actual code files by rendering Jinja2 templates. It maintains a single
    Jinja2 Environment instance with custom filters and configuration.

    The renderer handles both static templates (rendered once per project)
    and dynamic templates (rendered for each agent or component).
    """

    def __init__(self) -> None:
        self._env = Environment(
            loader=PackageLoader("agentforge", "templates"),
            autoescape=select_autoescape([]),   # Python code — no HTML escaping
            undefined=StrictUndefined,          # fail fast on missing variables
            trim_blocks=True,
            lstrip_blocks=True,
        )
        # Register custom filters
        self._env.filters["snake_case"]  = snake_case
        self._env.filters["pascal_case"] = pascal_case
        self._env.filters["upper_snake"] = upper_snake

    # ── Public API ────────────────────────────────────────────────────────────

    def render_all(self, config: ProjectConfig) -> list[tuple[Path, str]]:
        """
        Render every template for the given project configuration.

        This method renders all templates needed for a complete project scaffold,
        including both static templates (rendered once per project) and dynamic
        templates (rendered for each agent).

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
            content = self._render(tmpl_name, ctx)
            results.append((Path(rel_path), content))

        # Dynamic (per-agent) templates
        for agent in config.agents:
            agent_ctx = {**ctx, "agent": agent.model_dump()}
            content = self._render("agent.py.j2", agent_ctx)
            results.append((Path(f"backend/agents/{agent.key}_agent.py"), content))

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
        ctx = self._build_context(config)
        agent_ctx = {**ctx, "agent": agent.model_dump()}

        results = []
        # The agent module itself
        content = self._render("agent.py.j2", agent_ctx)
        results.append((Path(f"backend/agents/{agent.key}_agent.py"), content))
        # Re-render registry.py to include the new agent
        content = self._render("registry.py.j2", ctx)
        results.append((Path("backend/agents/registry.py"), content))
        return results

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _render(self, template_name: str, ctx: dict) -> str:
        """
        Render a single template with the given context.

        Args:
            template_name: Name of the template file (e.g., "agent.py.j2")
            ctx: Context dictionary with variables for the template

        Returns:
            The rendered template content as a string

        Raises:
            TemplateNotFound: If the template doesn't exist
            UndefinedError: If the template references undefined variables
        """
        # Validate template existence before attempting to render
        template_path = os.path.join("templates", template_name)
        if not self._template_exists(template_name):
            console.print(f"[red]✗[/red] Template not found: {template_name}")
            raise TemplateNotFound(template_name)

        try:
            tmpl = self._env.get_template(template_name)
            return tmpl.render(**ctx)
        except UndefinedError as e:
            console.print(f"[red]✗[/red] Template rendering error: {str(e)}")
            console.print("[yellow]![/yellow] Missing variable in template. Check your project configuration.")
            raise
        except Exception as e:
            console.print(f"[red]✗[/red] Unexpected error rendering template: {str(e)}")
            raise

    def _template_exists(self, template_name: str) -> bool:
        """
        Check if a template exists in the templates directory.

        Args:
            template_name: Name of the template file to check

        Returns:
            True if the template exists, False otherwise
        """
        try:
            self._env.get_template(template_name)
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
        # Observability aliases
        data["enable_tracing"]              = config.observability.enable_tracing
        data["tracing_provider"]            = config.observability.tracing_provider
        data["context_fields"]              = config.observability.context_fields
        data["log_rotation_bytes"]          = config.observability.log_rotation_bytes
        data["log_backup_count"]            = config.observability.log_backup_count
        data["structured_logging"]           = config.observability.structured_logging
        # Security aliases
        data["enable_auth"]                 = config.security.enable_auth
        data["api_key_env_var"]             = config.security.api_key_env_var
        data["enable_ip_pseudonymization"]  = config.security.enable_ip_pseudonymization
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
        # Top-level feature flags
        data["enable_provider_registry"]    = config.enable_provider_registry
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
    ("__init__.py.j2",                "backend/security/__init__.py"),
    ("__init__.py.j2",                "backend/config/__init__.py",
     lambda c: c.enable_provider_registry),
    ("__init__.py.j2",                "backend/tests/__init__.py",
     lambda c: c.observability.structured_logging),
    # ── Static (per-project) templates ────────────────────────────────────────
    ("base_agent.py.j2",            "backend/agents/base_agent.py"),
    ("registry.py.j2",              "backend/agents/registry.py"),
    ("state.py.j2",                 "backend/graph/state.py"),
    ("workflow.py.j2",              "backend/graph/workflow.py"),
    ("query_router_node.py.j2",     "backend/graph/nodes/query_router_node.py"),
    ("supervisor_node.py.j2",       "backend/graph/nodes/supervisor_node.py"),
    ("answer_node.py.j2",           "backend/graph/nodes/answer_node.py"),
    ("validation_node.py.j2",       "backend/graph/nodes/validation_node.py"),
    ("feedback_node.py.j2",         "backend/graph/nodes/feedback_node.py"),
    ("mcp_server.py.j2",            "backend/mcp_server.py"),
    ("main.py.j2",                  "backend/main.py"),
    (_resolve_logging_template,     "backend/observability/logging.py"),
    ("tracing.py.j2",               "backend/observability/tracing.py"),
    ("auth.py.j2",                  "backend/security/auth.py"),
    ("sanitizer.py.j2",             "backend/security/sanitizer.py"),
    ("logging_middleware.py.j2",    "backend/middleware/logging_middleware.py"),
    ("test_structlog_setup.py.j2",   "backend/tests/test_structlog_setup.py",
     lambda c: c.observability.structured_logging),
    ("requirements.txt.j2",         "requirements.txt"),
    ("env.j2",                      ".env.example"),
    ("README.md.j2",                "README.md"),
    ("gitignore.j2",                ".gitignore"),
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
]
