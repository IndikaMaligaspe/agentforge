"""
Tests for tool-kind rendering — TODO-v2-7.

Covers:
- Tagged-union schema: McpTool, HttpTool, AgentTool discriminated on 'kind'.
- Pydantic ValidationError for unknown 'kind' string.
- Backwards-compat: tool entry with no 'kind' defaults to 'kind="mcp"'.
- File presence / absence per tool mix (mcp-only, http-only, agent-only,
  mcp+http, all-three).
- AST-compile all generated files in each mix.
- tool_registry.py (when present) lists exactly the declared tool names.
- http_tool.py (when present) imports httpx and reads auth_env_var at runtime.
- agent_tool.py (when present) contains no JWT reimplementation — verified via
  AST-level check and string scan for jwt.decode / jwt.encode / PyJWKClient.
- No bare tool URL / timeout / auth-env-var literals in rendered templates
  (values must come from Jinja context).
- Mock HTTP tool call unit test: stub httpx.AsyncClient.request, assert correct
  URL / method / auth header.
- Mock agent tool call unit test: stub httpx.AsyncClient.post, assert
  Authorization header is set (stubbed JWT).
- requirements.txt: httpx appears as a runtime dep when http or agent tools
  present; absent (as a standalone runtime dep block) for mcp-only.
"""
from __future__ import annotations

import ast
import asyncio
import importlib.util
import sys
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentforge.engine.renderer import TemplateRenderer
from agentforge.schema.models import (
    AgentConfig,
    AgentTool,
    HttpTool,
    LLMModel,
    McpTool,
    ProjectConfig,
    ProjectMetadata,
    ToolConfig,
    WorkflowConfig,
)
from pydantic import ValidationError


# ── Helpers ───────────────────────────────────────────────────────────────────

def _render_map(config: ProjectConfig) -> dict[str, str]:
    """Render all templates and return a {relative_path: content} mapping."""
    renderer = TemplateRenderer()
    return {str(path): content for path, content in renderer.render_all(config)}


def _make_config(tools: list, project_name: str = "tool_test") -> ProjectConfig:
    """Build a minimal valid ProjectConfig with the given tool list."""
    return ProjectConfig(
        metadata=ProjectMetadata(
            name=project_name,
            description="Tool kind render test",
            python_version="3.11",
            author="Test Author",
            email="test@example.com",
        ),
        agents=[
            AgentConfig(
                key="sql",
                class_name="SqlAgent",
                llm_model=LLMModel.GPT4O_MINI,
                system_prompt="You are a helpful assistant.",
                needs_validation=False,
                tools=tools,
            )
        ],
        workflow=WorkflowConfig(default_intent="sql"),  # type: ignore[call-arg]
    )


# ── Tool mix fixtures ─────────────────────────────────────────────────────────

MCP_TOOL = McpTool(
    name="execute_sql",
    description="Run a SQL query",
    mcp_resource="execute_sql",
)

HTTP_TOOL = HttpTool(
    kind="http",
    name="fetch_data",
    description="Fetch data from REST API",
    url="https://api.example.com/data",
    method="GET",
    auth_env_var="REST_API_TOKEN",
    timeout_s=10.0,
)

AGENT_TOOL = AgentTool(
    kind="agent",
    name="downstream_agent",
    description="Call downstream AgentForge service",
    service_url="https://downstream.example.com",
    agent_key="analytics",
    auth_env_var="DOWNSTREAM_JWT",
)

TOOL_MIXES = [
    pytest.param([MCP_TOOL],                         id="mcp-only"),
    pytest.param([HTTP_TOOL],                         id="http-only"),
    pytest.param([AGENT_TOOL],                        id="agent-only"),
    pytest.param([MCP_TOOL, HTTP_TOOL],               id="mcp+http"),
    pytest.param([MCP_TOOL, HTTP_TOOL, AGENT_TOOL],   id="all-three"),
]


# ── File presence / absence per mix ──────────────────────────────────────────

@pytest.mark.parametrize("tools", TOOL_MIXES)
def test_mcp_client_present_iff_mcp_tool_present(tools):
    """backend/services/mcp_client.py must appear iff any tool has mcp_resource."""
    config = _make_config(tools)
    rendered = _render_map(config)
    has_mcp = any(getattr(t, "mcp_resource", None) for t in tools)
    if has_mcp:
        assert "backend/services/mcp_client.py" in rendered
    else:
        assert "backend/services/mcp_client.py" not in rendered


@pytest.mark.parametrize("tools", TOOL_MIXES)
def test_http_tool_present_iff_http_tool_declared(tools):
    """backend/services/http_tool.py must appear iff any tool has kind='http'."""
    config = _make_config(tools)
    rendered = _render_map(config)
    has_http = any(t.kind == "http" for t in tools)
    if has_http:
        assert "backend/services/http_tool.py" in rendered, (
            "http_tool.py must be rendered when http tools are present"
        )
    else:
        assert "backend/services/http_tool.py" not in rendered, (
            "http_tool.py must NOT be rendered when no http tools are present"
        )


@pytest.mark.parametrize("tools", TOOL_MIXES)
def test_agent_tool_present_iff_agent_tool_declared(tools):
    """backend/services/agent_tool.py must appear iff any tool has kind='agent'."""
    config = _make_config(tools)
    rendered = _render_map(config)
    has_agent = any(t.kind == "agent" for t in tools)
    if has_agent:
        assert "backend/services/agent_tool.py" in rendered, (
            "agent_tool.py must be rendered when agent tools are present"
        )
    else:
        assert "backend/services/agent_tool.py" not in rendered, (
            "agent_tool.py must NOT be rendered when no agent tools are present"
        )


@pytest.mark.parametrize("tools", TOOL_MIXES)
def test_tool_registry_present_iff_http_or_agent_tool_declared(tools):
    """backend/services/tool_registry.py appears only when http or agent tools present."""
    config = _make_config(tools)
    rendered = _render_map(config)
    has_non_mcp = any(t.kind in ("http", "agent") for t in tools)
    if has_non_mcp:
        assert "backend/services/tool_registry.py" in rendered, (
            "tool_registry.py must be rendered when http or agent tools are present"
        )
    else:
        assert "backend/services/tool_registry.py" not in rendered, (
            "tool_registry.py must NOT be rendered for mcp-only projects"
        )


# ── AST compile all generated files ──────────────────────────────────────────

@pytest.mark.parametrize("tools", TOOL_MIXES)
def test_all_generated_python_files_ast_compile(tools):
    """Every generated .py file in each tool mix must parse without SyntaxError."""
    config = _make_config(tools)
    rendered = _render_map(config)
    errors = []
    for rel_path, content in rendered.items():
        if not rel_path.endswith(".py"):
            continue
        try:
            ast.parse(content)
        except SyntaxError as e:
            errors.append(f"{rel_path}: {e}")
    assert not errors, "SyntaxError in generated files:\n" + "\n".join(errors)


# ── tool_registry.py lists exactly the declared tool names ───────────────────

def test_tool_registry_lists_exactly_declared_tool_names_http_agent():
    """tool_registry.py must reference exactly the declared http + agent tool names."""
    tools = [HTTP_TOOL, AGENT_TOOL]
    config = _make_config(tools)
    rendered = _render_map(config)
    registry_src = rendered.get("backend/services/tool_registry.py", "")
    assert registry_src, "tool_registry.py must be rendered for http+agent mix"
    # Both declared names must appear as registry keys
    assert '"fetch_data"' in registry_src, "HTTP tool name must appear in registry"
    assert '"downstream_agent"' in registry_src, "Agent tool name must appear in registry"


def test_tool_registry_all_three_tool_names_present():
    """tool_registry.py for all-three mix must reference all declared names."""
    tools = [MCP_TOOL, HTTP_TOOL, AGENT_TOOL]
    config = _make_config(tools)
    rendered = _render_map(config)
    registry_src = rendered.get("backend/services/tool_registry.py", "")
    assert registry_src, "tool_registry.py must be rendered for all-three mix"
    assert '"fetch_data"' in registry_src
    assert '"downstream_agent"' in registry_src
    # MCP tools are aggregated from get_mcp_tools() — their names come from MCP server
    # at runtime, not statically. Verify the MCP aggregation import is present.
    assert "get_mcp_tools" in registry_src


# ── http_tool.py content checks ───────────────────────────────────────────────

def test_http_tool_uses_httpx():
    """http_tool.py must import httpx."""
    config = _make_config([HTTP_TOOL])
    rendered = _render_map(config)
    content = rendered["backend/services/http_tool.py"]
    assert "import httpx" in content


def test_http_tool_reads_auth_env_var_at_runtime():
    """http_tool.py must call os.environ.get with the auth_env_var name at runtime."""
    config = _make_config([HTTP_TOOL])
    rendered = _render_map(config)
    content = rendered["backend/services/http_tool.py"]
    # The auth_env_var value must appear in the generated code (passed to _get_bearer_token)
    assert "REST_API_TOKEN" in content


def test_http_tool_defers_openapi_ingestion():
    """http_tool.py must include the 'OpenAPI ingestion deferred' TODO comment."""
    config = _make_config([HTTP_TOOL])
    rendered = _render_map(config)
    content = rendered["backend/services/http_tool.py"]
    assert "OpenAPI ingestion" in content


# ── agent_tool.py content checks ─────────────────────────────────────────────

def test_agent_tool_no_jwt_reimplementation():
    """agent_tool.py must not reimplement JWT logic — verified via AST and string scan."""
    config = _make_config([AGENT_TOOL])
    rendered = _render_map(config)
    src = rendered["backend/services/agent_tool.py"]
    tree = ast.parse(src)
    # No function with JWT-verifier semantics
    forbidden_fns = {"verify_token", "create_access_token", "mint_token", "decode_token"}
    defined_fns = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert not (forbidden_fns & defined_fns), (
        f"agent_tool.py must not define JWT functions: {forbidden_fns & defined_fns}"
    )
    # No module-level JWT-library calls
    assert "jwt.decode" not in src
    assert "jwt.encode" not in src
    assert "PyJWKClient" not in src
    # Docstring references the authoritative verifier path
    assert "backend.security.jwt" in src or "security.jwt" in src


def test_agent_tool_sets_authorization_header():
    """agent_tool.py must include 'Authorization' header setup."""
    config = _make_config([AGENT_TOOL])
    rendered = _render_map(config)
    content = rendered["backend/services/agent_tool.py"]
    assert "Authorization" in content


def test_agent_tool_handles_401_403():
    """agent_tool.py must have explicit handling for 401/403 responses."""
    config = _make_config([AGENT_TOOL])
    rendered = _render_map(config)
    content = rendered["backend/services/agent_tool.py"]
    assert "401" in content
    assert "403" in content


# ── No bare literals from context in templates ────────────────────────────────

def test_http_tool_url_comes_from_context_not_hardcoded():
    """The HTTP tool URL must appear in generated code (sourced from Jinja context)."""
    config = _make_config([HTTP_TOOL])
    rendered = _render_map(config)
    content = rendered["backend/services/http_tool.py"]
    # The URL from config must be in the generated code
    assert "api.example.com" in content


def test_http_tool_timeout_comes_from_context():
    """The HTTP tool timeout must appear in generated code (from Jinja context)."""
    config = _make_config([HTTP_TOOL])
    rendered = _render_map(config)
    content = rendered["backend/services/http_tool.py"]
    # HTTP_TOOL.timeout_s = 10.0 — must appear in generated code
    assert "10.0" in content


def test_agent_tool_service_url_comes_from_context():
    """The agent tool service_url must appear in generated code."""
    config = _make_config([AGENT_TOOL])
    rendered = _render_map(config)
    content = rendered["backend/services/agent_tool.py"]
    assert "downstream.example.com" in content


# ── Tagged-union schema validation ────────────────────────────────────────────

def test_unknown_kind_raises_validation_error():
    """A tool entry with an unknown 'kind' must raise Pydantic ValidationError."""
    with pytest.raises(ValidationError):
        ProjectConfig(
            metadata=ProjectMetadata(
                name="bad_proj",
                description="test",
                python_version="3.11",
                author="X",
                email="x@x.com",
            ),
            agents=[
                AgentConfig(
                    key="sql",
                    class_name="SqlAgent",
                    tools=[{  # type: ignore[list-item]
                        "kind": "grpc",  # unknown kind
                        "name": "bad_tool",
                        "description": "test",
                    }],
                )
            ],
            workflow=WorkflowConfig(default_intent="sql"),  # type: ignore[call-arg]
        )


def test_kind_mcp_accepts_legacy_mcp_shape():
    """kind='mcp' must accept the legacy MCP tool shape (name + description + mcp_resource)."""
    tool = McpTool(name="execute_sql", description="run sql", mcp_resource="execute_sql")
    assert tool.kind == "mcp"
    assert tool.mcp_resource == "execute_sql"


def test_kind_http_requires_url():
    """kind='http' must require the 'url' field."""
    with pytest.raises(ValidationError):
        HttpTool(kind="http", name="bad_tool", description="test")  # missing url


def test_kind_agent_requires_service_url_and_agent_key():
    """kind='agent' must require both 'service_url' and 'agent_key'."""
    with pytest.raises(ValidationError):
        AgentTool(kind="agent", name="bad_tool", description="test")  # missing both
    with pytest.raises(ValidationError):
        AgentTool(
            kind="agent",
            name="bad_tool",
            description="test",
            service_url="https://example.com",
            # missing agent_key
        )


def test_http_tool_timeout_gt_zero():
    """HttpTool.timeout_s must be > 0."""
    with pytest.raises(ValidationError):
        HttpTool(
            kind="http",
            name="bad_tool",
            description="test",
            url="https://example.com",
            timeout_s=0,
        )


def test_http_tool_timeout_le_600():
    """HttpTool.timeout_s must be <= 600."""
    with pytest.raises(ValidationError):
        HttpTool(
            kind="http",
            name="bad_tool",
            description="test",
            url="https://example.com",
            timeout_s=601,
        )


# ── Backwards-compat: missing 'kind' defaults to 'mcp' ───────────────────────

def test_tool_without_kind_defaults_to_mcp_via_before_validator():
    """A tool dict without 'kind' must be rewritten to kind='mcp' by the before-validator."""
    import yaml

    raw = yaml.safe_load("""
metadata:
  name: legacy_proj
  description: test
  python_version: '3.11'
  author: X
  email: x@x.com
agents:
  - key: sql
    class_name: SqlAgent
    tools:
      - name: execute_sql
        description: Run a SQL query
        mcp_resource: execute_sql
workflow:
  default_intent: sql
""")
    config = ProjectConfig.model_validate(raw)
    assert config.agents[0].tools[0].kind == "mcp", (
        "Tool without 'kind' must default to kind='mcp'"
    )


def test_tool_config_alias_still_works():
    """ToolConfig is an alias for McpTool — existing imports must not break."""
    # ToolConfig IS McpTool
    tool = ToolConfig(name="exec_sql", description="run sql", mcp_resource="execute_sql")
    assert tool.kind == "mcp"
    assert isinstance(tool, McpTool)


# ── requirements.txt httpx gating ────────────────────────────────────────────

def _render_requirements(config: ProjectConfig) -> str:
    renderer = TemplateRenderer()
    ctx = renderer._build_context(config)
    return renderer._env.get_template("requirements.txt.j2").render(**ctx)


def test_requirements_includes_httpx_runtime_block_for_http_tool():
    """requirements.txt must include the httpx runtime dep block when http tools present."""
    config = _make_config([HTTP_TOOL])
    req = _render_requirements(config)
    # The runtime httpx block (distinct from dev httpx) should appear
    assert "httpx" in req
    # Specifically the runtime comment block
    assert "HTTP client" in req


def test_requirements_includes_httpx_runtime_block_for_agent_tool():
    """requirements.txt must include the httpx runtime dep block when agent tools present."""
    config = _make_config([AGENT_TOOL])
    req = _render_requirements(config)
    assert "httpx" in req
    assert "HTTP client" in req


def test_requirements_no_extra_httpx_block_for_mcp_only():
    """requirements.txt must NOT include the runtime httpx block for mcp-only projects."""
    config = _make_config([MCP_TOOL])
    req = _render_requirements(config)
    # The runtime comment block should not appear (httpx is only in dev tools)
    assert "HTTP client" not in req


# ── Mock HTTP tool call unit test ─────────────────────────────────────────────

def _exec_module(source: str, module_name: str) -> types.ModuleType:
    """Execute generated Python source in a fresh module and return it.

    Injects the minimum stub modules required to satisfy imports, then removes
    them from sys.modules on return to avoid polluting the global import cache
    (which would break subsequent tests that import the real 'backend' package).
    """
    stub_keys = ["backend", "backend.observability", "backend.observability.logging"]

    # Save any pre-existing entries so we can restore them
    saved = {k: sys.modules[k] for k in stub_keys if k in sys.modules}

    # Install stubs
    stub_logging = types.ModuleType("backend.observability.logging")
    stub_logging.get_logger = lambda name: MagicMock()  # type: ignore[assignment]
    stub_backend = types.ModuleType("backend")
    stub_observability = types.ModuleType("backend.observability")
    sys.modules["backend"] = stub_backend
    sys.modules["backend.observability"] = stub_observability
    sys.modules["backend.observability.logging"] = stub_logging

    try:
        mod = types.ModuleType(module_name)
        exec(compile(source, module_name, "exec"), mod.__dict__)  # noqa: S102
        return mod
    finally:
        # Restore sys.modules to the state before we installed stubs
        for key in stub_keys:
            if key in saved:
                sys.modules[key] = saved[key]
            else:
                sys.modules.pop(key, None)


def test_http_tool_call_uses_correct_url_method_auth():
    """Stubbing httpx.AsyncClient, the generated HTTP tool must call with correct params."""
    config = _make_config([HTTP_TOOL])
    rendered = _render_map(config)
    source = rendered["backend/services/http_tool.py"]

    # Set up env var for auth
    import os

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"result": "ok"})

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.request = AsyncMock(return_value=mock_response)

    with patch.dict(os.environ, {"REST_API_TOKEN": "test-token-abc"}):
        with patch("httpx.AsyncClient", return_value=mock_client):
            mod = _exec_module(source, "backend.services.http_tool")
            result = asyncio.get_event_loop().run_until_complete(mod.fetch_data())

    # Verify the call was made with the right method and that auth header was set
    mock_client.request.assert_called_once()
    call_args = mock_client.request.call_args
    assert call_args[0][0] == "GET", "Method must be GET"
    assert "api.example.com" in str(call_args[0][1]), "URL must contain the configured host"
    headers = call_args[1].get("headers") or call_args[0][2] if len(call_args[0]) > 2 else {}
    if not headers and "headers" in call_args[1]:
        headers = call_args[1]["headers"]
    assert "Authorization" in headers, "Authorization header must be set"
    assert headers["Authorization"] == "Bearer test-token-abc"


# ── Mock agent tool call unit test ────────────────────────────────────────────

def test_agent_tool_call_sets_authorization_header():
    """Stubbing httpx.AsyncClient, the generated agent tool must set Authorization header."""
    config = _make_config([AGENT_TOOL])
    rendered = _render_map(config)
    source = rendered["backend/services/agent_tool.py"]

    import os

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"output": "done"})

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch.dict(os.environ, {"DOWNSTREAM_JWT": "jwt-token-xyz"}):
        with patch("httpx.AsyncClient", return_value=mock_client):
            mod = _exec_module(source, "backend.services.agent_tool")
            result = asyncio.get_event_loop().run_until_complete(mod.downstream_agent())

    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args[1]
    headers = call_kwargs.get("headers", {})
    assert "Authorization" in headers, "Authorization header must be set"
    assert headers["Authorization"] == "Bearer jwt-token-xyz"
