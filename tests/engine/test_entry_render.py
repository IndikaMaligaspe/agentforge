"""
Tests for the entry type overlays (TODO-v2-6).

Covers:
- Parametrize over entry.type in {"intent_router", "passthrough", "direct"}:
  - intent_router: no passthrough/direct files emitted; query_router_node emitted.
  - passthrough: passthrough_node.py emitted; direct_entry.py absent.
  - direct: direct_entry.py emitted; passthrough_node.py absent.
  - main.py contains the correct endpoint shape for each type (via regex).
- Hardcoded-values check: no bare model strings in the two new templates.
- AST-compile: all rendered .py files parse as valid Python.
- Structural assertion: rendered main.py declares the correct Pydantic request model
  fields per entry type (AST-based — does not require importing the generated module).
- TestClient integration tests: render scaffold to tmp_path, stub heavy deps, POST to
  endpoint, assert 200 with expected shape.
"""
from __future__ import annotations

import ast
import contextlib
import importlib
import importlib.util
import logging
import re
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import MagicMock

import pytest

from agentforge.engine.renderer import TemplateRenderer, _is_passthrough_entry, _is_direct_entry
from agentforge.schema.models import ProjectConfig


# ── Fixtures / helpers ────────────────────────────────────────────────────────

_ENTRY_TEMPLATES_DIR = (
    Path(__file__).parent.parent.parent
    / "agentforge"
    / "templates"
    / "patterns"
    / "_entry"
)


def _make_config(entry_type: str) -> ProjectConfig:
    """Build a minimal valid ProjectConfig with the given entry.type."""
    base: dict = {
        "metadata": {
            "name": "entry_test_project",
            "description": "Entry-type render test",
            "python_version": "3.11",
            "author": "Test Author",
            "email": "test@example.com",
        },
        "agents": [
            {
                "key": "sql",
                "class_name": "SqlAgent",
                "llm_model": "gpt-4o-mini",
                "system_prompt": "You are a SQL assistant.",
                "needs_validation": False,
            }
        ],
        "database": {"backend": "postgres", "tables": []},
        "workflow": {
            "default_intent": "sql",
            "enable_feedback_loop": False,
            "enable_validation_node": False,
        },
        "entry": {"type": entry_type},
        "pattern": "orchestrator",
        "orchestrator": {"kind": "llm"},
    }
    return ProjectConfig.model_validate(base)


def _render_map(config: ProjectConfig) -> dict[str, str]:
    """Render all templates and return {relative_path: content}."""
    renderer = TemplateRenderer()
    return {str(path): content for path, content in renderer.render_all(config)}


# ── Predicate tests ───────────────────────────────────────────────────────────


def test_passthrough_predicate_true_for_passthrough() -> None:
    """_is_passthrough_entry returns True only for entry.type == 'passthrough'."""
    assert _is_passthrough_entry(_make_config("passthrough")) is True


def test_passthrough_predicate_false_for_intent_router() -> None:
    assert _is_passthrough_entry(_make_config("intent_router")) is False


def test_passthrough_predicate_false_for_direct() -> None:
    assert _is_passthrough_entry(_make_config("direct")) is False


def test_direct_predicate_true_for_direct() -> None:
    """_is_direct_entry returns True only for entry.type == 'direct'."""
    assert _is_direct_entry(_make_config("direct")) is True


def test_direct_predicate_false_for_intent_router() -> None:
    assert _is_direct_entry(_make_config("intent_router")) is False


def test_direct_predicate_false_for_passthrough() -> None:
    assert _is_direct_entry(_make_config("passthrough")) is False


# ── File emission checks ──────────────────────────────────────────────────────

_PASSTHROUGH_PATH = "backend/graph/nodes/passthrough_node.py"
_DIRECT_PATH = "backend/graph/direct_entry.py"
_ROUTER_PATH = "backend/graph/nodes/query_router_node.py"


@pytest.mark.parametrize(
    "entry_type,should_emit",
    [
        ("intent_router", True),
        ("passthrough", False),
        ("direct", False),
    ],
)
def test_router_node_emission_gated_on_entry_type(
    entry_type: str, should_emit: bool
) -> None:
    """query_router_node.py is emitted only for entry_type=intent_router.

    passthrough and direct replace the router with their own entry nodes;
    emitting query_router_node in those paths would produce dead scaffold code.
    """
    config = _make_config(entry_type)
    rendered = _render_map(config)
    if should_emit:
        assert _ROUTER_PATH in rendered, (
            f"query_router_node.py must be emitted for entry_type={entry_type!r}"
        )
    else:
        assert _ROUTER_PATH not in rendered, (
            f"query_router_node.py must NOT be emitted for entry_type={entry_type!r} "
            f"(would be dead code since main.py does not import it)"
        )


def test_intent_router_no_passthrough_file() -> None:
    """intent_router: passthrough_node.py must NOT be emitted."""
    rendered = _render_map(_make_config("intent_router"))
    assert _PASSTHROUGH_PATH not in rendered, (
        "passthrough_node.py must be absent for intent_router entry"
    )


def test_intent_router_no_direct_file() -> None:
    """intent_router: direct_entry.py must NOT be emitted."""
    rendered = _render_map(_make_config("intent_router"))
    assert _DIRECT_PATH not in rendered, (
        "direct_entry.py must be absent for intent_router entry"
    )


def test_passthrough_emits_passthrough_node() -> None:
    """passthrough: passthrough_node.py must be emitted."""
    rendered = _render_map(_make_config("passthrough"))
    assert _PASSTHROUGH_PATH in rendered, (
        "passthrough_node.py must be emitted for passthrough entry"
    )


def test_passthrough_no_direct_file() -> None:
    """passthrough: direct_entry.py must NOT be emitted."""
    rendered = _render_map(_make_config("passthrough"))
    assert _DIRECT_PATH not in rendered, (
        "direct_entry.py must be absent for passthrough entry"
    )


def test_direct_emits_direct_entry() -> None:
    """direct: direct_entry.py must be emitted."""
    rendered = _render_map(_make_config("direct"))
    assert _DIRECT_PATH in rendered, (
        "direct_entry.py must be emitted for direct entry"
    )


def test_direct_no_passthrough_file() -> None:
    """direct: passthrough_node.py must NOT be emitted."""
    rendered = _render_map(_make_config("direct"))
    assert _PASSTHROUGH_PATH not in rendered, (
        "passthrough_node.py must be absent for direct entry"
    )


# ── AST-compile: all .py files parse as valid Python ─────────────────────────


@pytest.mark.parametrize("entry_type", ["intent_router", "passthrough", "direct"])
def test_all_py_files_compile(entry_type: str) -> None:
    """All rendered .py files for the given entry type must parse as valid Python."""
    config = _make_config(entry_type)
    rendered = _render_map(config)
    failures: list[str] = []
    for rel_path, content in rendered.items():
        if not rel_path.endswith(".py"):
            continue
        try:
            ast.parse(content)
        except SyntaxError as exc:
            failures.append(f"{rel_path}: {exc}")
    assert not failures, (
        f"Generated .py files with syntax errors for entry_type={entry_type!r}:\n"
        + "\n".join(failures)
    )


# ── main.py endpoint shape: regex on rendered source ─────────────────────────


def test_intent_router_main_py_has_query_field() -> None:
    """intent_router main.py must declare a QueryRequest model with a 'query' field."""
    rendered = _render_map(_make_config("intent_router"))
    main_py = rendered.get("backend/main.py", "")
    # QueryRequest must have `query: str = Field(...)` — regex over rendered source
    assert re.search(r"class\s+QueryRequest\s*\(BaseModel\)", main_py), (
        "intent_router main.py must declare QueryRequest(BaseModel)"
    )
    assert re.search(r"query\s*:\s*str\s*=\s*Field\(", main_py), (
        "intent_router main.py QueryRequest must have a 'query' str field"
    )
    # Must NOT have intent field in QueryRequest
    assert not re.search(r"intent\s*:\s*str\s*=\s*Field\(", main_py), (
        "intent_router main.py QueryRequest must not have an 'intent' field"
    )


def test_passthrough_main_py_has_intent_and_query_fields() -> None:
    """passthrough main.py must declare a QueryRequest model with both 'intent' and 'query' fields."""
    rendered = _render_map(_make_config("passthrough"))
    main_py = rendered.get("backend/main.py", "")
    assert re.search(r"class\s+QueryRequest\s*\(BaseModel\)", main_py), (
        "passthrough main.py must declare QueryRequest(BaseModel)"
    )
    assert re.search(r"intent\s*:\s*str\s*=\s*Field\(", main_py), (
        "passthrough main.py QueryRequest must have an 'intent' str field"
    )
    assert re.search(r"query\s*:\s*str\s*=\s*Field\(", main_py), (
        "passthrough main.py QueryRequest must have a 'query' str field"
    )


def test_direct_main_py_imports_direct_entry_request() -> None:
    """direct main.py must import DirectEntryRequest and not declare QueryRequest."""
    rendered = _render_map(_make_config("direct"))
    main_py = rendered.get("backend/main.py", "")
    assert re.search(r"from\s+graph\.direct_entry\s+import\s+DirectEntryRequest", main_py), (
        "direct main.py must import DirectEntryRequest from graph.direct_entry"
    )
    # QueryRequest must NOT be declared for direct entry (DirectEntryRequest is used instead)
    assert not re.search(r"class\s+QueryRequest\s*\(BaseModel\)", main_py), (
        "direct main.py must not declare QueryRequest — DirectEntryRequest is used"
    )


def test_intent_router_main_py_endpoint_uses_query_request() -> None:
    """intent_router endpoint must use QueryRequest as the parameter type."""
    rendered = _render_map(_make_config("intent_router"))
    main_py = rendered.get("backend/main.py", "")
    # The handle_query function must accept QueryRequest
    assert re.search(r"def\s+handle_query\s*\(\s*request\s*:\s*QueryRequest", main_py), (
        "intent_router main.py handle_query must accept QueryRequest"
    )


def test_passthrough_main_py_endpoint_is_async() -> None:
    """passthrough endpoint must be async (it awaits passthrough_node)."""
    rendered = _render_map(_make_config("passthrough"))
    main_py = rendered.get("backend/main.py", "")
    assert re.search(r"async\s+def\s+handle_query\s*\(\s*request\s*:\s*QueryRequest", main_py), (
        "passthrough main.py handle_query must be 'async def' (awaits passthrough_node)"
    )


def test_direct_main_py_endpoint_uses_direct_entry_request() -> None:
    """direct endpoint must accept DirectEntryRequest."""
    rendered = _render_map(_make_config("direct"))
    main_py = rendered.get("backend/main.py", "")
    assert re.search(r"def\s+handle_query\s*\(\s*request\s*:\s*DirectEntryRequest", main_py), (
        "direct main.py handle_query must accept DirectEntryRequest"
    )


def test_main_py_error_helper_present_for_passthrough_and_direct() -> None:
    """passthrough and direct entry types must render _make_error_response in main.py."""
    for entry_type in ("passthrough", "direct"):
        rendered = _render_map(_make_config(entry_type))
        main_py = rendered.get("backend/main.py", "")
        assert re.search(r"def\s+_make_error_response\s*\(", main_py), (
            f"main.py for entry_type={entry_type!r} must declare _make_error_response helper"
        )


def test_intent_router_main_py_no_error_helper() -> None:
    """intent_router must NOT render _make_error_response — it uses inline error handling
    for byte-identity with the legacy scaffold snapshot."""
    rendered = _render_map(_make_config("intent_router"))
    main_py = rendered.get("backend/main.py", "")
    assert not re.search(r"def\s+_make_error_response\s*\(", main_py), (
        "intent_router main.py must NOT declare _make_error_response — "
        "inline error handling is required for byte-identity with the HEAD snapshot"
    )


# ── AST-based structural assertions on direct_entry.py ───────────────────────


def test_direct_entry_request_model_fields_via_ast() -> None:
    """direct_entry.py must declare a DirectEntryRequest class with 'intent' and 'inputs' fields."""
    rendered = _render_map(_make_config("direct"))
    source = rendered.get(_DIRECT_PATH, "")
    assert source, f"{_DIRECT_PATH} was not rendered"

    tree = ast.parse(source)

    # Find the DirectEntryRequest class definition
    class_defs = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    class_names = [c.name for c in class_defs]
    assert "DirectEntryRequest" in class_names, (
        "direct_entry.py must declare a class named DirectEntryRequest"
    )

    # Find annotated assignments in DirectEntryRequest for 'intent' and 'inputs'
    dr_class = next(c for c in class_defs if c.name == "DirectEntryRequest")
    ann_targets = {
        node.target.id
        for node in ast.walk(dr_class)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    assert "intent" in ann_targets, (
        "DirectEntryRequest must have an 'intent' annotated field"
    )
    assert "inputs" in ann_targets, (
        "DirectEntryRequest must have an 'inputs' annotated field"
    )


# ── Hardcoded-values check: templates must not contain bare model strings ─────


def test_passthrough_node_template_no_hardcoded_model() -> None:
    """passthrough_node.py.j2 must not contain bare model name strings outside Jinja expressions."""
    template_path = _ENTRY_TEMPLATES_DIR / "passthrough_node.py.j2"
    assert template_path.exists(), f"Template not found: {template_path}"
    raw = template_path.read_text(encoding="utf-8")

    # Strip all Jinja2 blocks (expressions and statements), then check
    # that no bare GPT/Claude model string remains in the static text.
    jinja_stripped = re.sub(r"\{[{%#].*?[}%#]\}", "", raw, flags=re.DOTALL)

    # Check for bare model name literals (e.g. "gpt-4o-mini", "claude-3-haiku-...")
    assert not re.search(r'"gpt-\d', jinja_stripped), (
        "passthrough_node.py.j2 contains a bare GPT model name string. "
        "Use {{ router_llm_model }} instead."
    )
    assert not re.search(r'"claude-\d', jinja_stripped), (
        "passthrough_node.py.j2 contains a bare Claude model name string. "
        "Use {{ router_llm_model }} instead."
    )


def test_direct_entry_template_no_hardcoded_intent_values() -> None:
    """direct_entry.py.j2 must not contain bare intent strings outside Jinja expressions."""
    template_path = _ENTRY_TEMPLATES_DIR / "direct_entry.py.j2"
    assert template_path.exists(), f"Template not found: {template_path}"
    raw = template_path.read_text(encoding="utf-8")

    jinja_stripped = re.sub(r"\{[{%#].*?[}%#]\}", "", raw, flags=re.DOTALL)

    # Check that no bare intent values (like "sql", "search") appear as string literals
    # adjacent to intent-related keywords in static text.
    # We allow the words in comments/docstrings; the key constraint is no Field(default="sql").
    assert not re.search(r'Field\s*\(\s*["\'](?:sql|search|analytics|data)["\']', jinja_stripped), (
        "direct_entry.py.j2 contains a hardcoded intent value in a Field(...) default. "
        "Intent values must come from config context, not be baked into the template."
    )


# ── No Madgicx strings ────────────────────────────────────────────────────────


@pytest.mark.parametrize("entry_type", ["intent_router", "passthrough", "direct"])
def test_no_madgicx_strings(entry_type: str) -> None:
    """No rendered file must contain 'madgicx' (case-insensitive) for any entry type."""
    config = _make_config(entry_type)
    rendered = _render_map(config)
    violations = [
        path for path, content in rendered.items() if "madgicx" in content.lower()
    ]
    assert not violations, (
        f"'madgicx' found in rendered files for entry_type={entry_type!r}: {violations}"
    )


# ── TestClient integration tests ──────────────────────────────────────────────
#
# Strategy: render the scaffold to tmp_path, register stub modules in sys.modules
# so the heavy project-runtime deps (observability, middleware, security, graph)
# resolve without a real LangGraph/LangChain install, then import backend.main,
# grab the FastAPI `app`, wrap in TestClient, and POST to the first endpoint.
#
# The stub pattern mirrors test_planner_precheck_node_real_import in
# tests/engine/test_planner_render.py.


def _make_observability_stubs() -> dict[str, types.ModuleType]:
    """Return a dict of module_name -> stub for the observability sub-package."""

    @contextlib.contextmanager
    def _noop_execution_time(logger: Any, label: str) -> Iterator[None]:  # noqa: WPS430
        yield

    obs_pkg = types.ModuleType("observability")
    obs_log = types.ModuleType("observability.logging")
    obs_log.get_logger = lambda name: logging.getLogger(name)  # type: ignore[attr-defined]

    class _RequestContext:
        @staticmethod
        def get_request_id() -> str:
            return "test-request-id"

    obs_log.RequestContext = _RequestContext  # type: ignore[attr-defined]
    obs_log.log_with_props = lambda logger, level, msg, **kw: None  # type: ignore[attr-defined]
    obs_log.log_execution_time = _noop_execution_time  # type: ignore[attr-defined]
    obs_pkg.logging = obs_log  # type: ignore[attr-defined]

    obs_tracing = types.ModuleType("observability.tracing")
    obs_tracing.trace_agent_run = lambda query: {"final_answer": "traced answer"}  # type: ignore[attr-defined]

    class _FakeLangfuse:
        def auth_check(self) -> None:
            pass

    obs_tracing.langfuse = _FakeLangfuse()  # type: ignore[attr-defined]
    obs_pkg.tracing = obs_tracing  # type: ignore[attr-defined]

    return {
        "observability": obs_pkg,
        "observability.logging": obs_log,
        "observability.tracing": obs_tracing,
    }


def _make_middleware_stub() -> dict[str, types.ModuleType]:
    """Return stubs for middleware sub-package (LoggingMiddleware)."""
    from starlette.middleware.base import BaseHTTPMiddleware

    class _NoopLoggingMiddleware(BaseHTTPMiddleware):  # noqa: WPS431
        async def dispatch(self, request: Any, call_next: Any) -> Any:  # noqa: WPS430
            return await call_next(request)

    mw_pkg = types.ModuleType("middleware")
    mw_log = types.ModuleType("middleware.logging_middleware")
    mw_log.LoggingMiddleware = _NoopLoggingMiddleware  # type: ignore[attr-defined]
    mw_pkg.logging_middleware = mw_log  # type: ignore[attr-defined]

    return {
        "middleware": mw_pkg,
        "middleware.logging_middleware": mw_log,
    }


def _make_security_stub() -> dict[str, types.ModuleType]:
    """Return stubs for security sub-package (sanitizer; auth is only imported for api_key)."""
    sec_pkg = types.ModuleType("security")
    sec_san = types.ModuleType("security.sanitizer")
    sec_san.sanitize_for_log = lambda s: s  # type: ignore[attr-defined]
    sec_pkg.sanitizer = sec_san  # type: ignore[attr-defined]

    return {
        "security": sec_pkg,
        "security.sanitizer": sec_san,
    }


def _make_graph_stubs(
    final_answer: str = "stub answer",
    direct_entry_path: Path | None = None,
) -> dict[str, types.ModuleType]:
    """Return stubs for graph.workflow (and optionally graph.direct_entry).

    Args:
        final_answer: The value returned under the 'final_answer' key by the
            mock workflow invocation.
        direct_entry_path: When provided (direct entry type), the path to the
            rendered direct_entry.py on disk.  The file is loaded via
            ``importlib.util`` and registered as ``graph.direct_entry`` so that
            ``from graph.direct_entry import DirectEntryRequest`` resolves without
            a real project runtime.
    """
    mock_workflow = MagicMock()
    mock_workflow.invoke.return_value = {"final_answer": final_answer}

    graph_pkg = types.ModuleType("graph")
    graph_wf = types.ModuleType("graph.workflow")
    graph_wf.get_workflow = lambda: mock_workflow  # type: ignore[attr-defined]
    graph_pkg.workflow = graph_wf  # type: ignore[attr-defined]

    result: dict[str, types.ModuleType] = {
        "graph": graph_pkg,
        "graph.workflow": graph_wf,
    }

    if direct_entry_path is not None:
        # Load the rendered direct_entry.py so DirectEntryRequest is a real
        # Pydantic model (pydantic is available in the test environment).
        spec = importlib.util.spec_from_file_location("graph.direct_entry", direct_entry_path)
        de_mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(de_mod)  # type: ignore[union-attr]
        graph_pkg.direct_entry = de_mod  # type: ignore[attr-defined]
        result["graph.direct_entry"] = de_mod

    return result


def _make_agents_stub() -> dict[str, types.ModuleType]:
    """Return stubs for the agents package (AgentRegistry, lifespan warm-up)."""
    agents_pkg = types.ModuleType("agents")
    agents_reg = types.ModuleType("agents.registry")

    class _AgentRegistry:
        @staticmethod
        def get_all_keys() -> list[str]:
            return ["sql"]

    agents_reg.AgentRegistry = _AgentRegistry  # type: ignore[attr-defined]
    agents_pkg.registry = agents_reg  # type: ignore[attr-defined]

    return {
        "agents": agents_pkg,
        "agents.registry": agents_reg,
    }


@contextmanager
def _scaffold_client_context(
    tmp_path: Path,
    entry_type: str,
    extra_stubs: dict[str, types.ModuleType] | None = None,
) -> Iterator[Any]:
    """Context manager that renders the scaffold, stubs sys.modules, and yields a TestClient.

    On exit the context restores sys.path and removes all injected modules from
    sys.modules so test isolation is preserved.

    Args:
        tmp_path: pytest-provided temporary directory for the rendered project.
        entry_type: One of "intent_router", "passthrough", "direct".
        extra_stubs: Additional module stubs to inject (e.g. passthrough_node stubs).

    Yields:
        A ``fastapi.testclient.TestClient`` wrapping the rendered FastAPI app.
    """
    from fastapi.testclient import TestClient

    config = _make_config(entry_type)
    rendered = _render_map(config)

    # Write all rendered files to disk so the package tree is navigable.
    for rel_path, content in rendered.items():
        dest = tmp_path / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")

    # For the direct entry type, the rendered direct_entry.py is imported at
    # module level by main.py as ``from graph.direct_entry import DirectEntryRequest``.
    # We load it from disk so DirectEntryRequest is a real Pydantic model rather
    # than a plain stub attribute.
    direct_entry_path: Path | None = None
    if entry_type == "direct":
        direct_entry_path = tmp_path / "backend" / "graph" / "direct_entry.py"

    stubs: dict[str, types.ModuleType] = {}
    stubs.update(_make_observability_stubs())
    stubs.update(_make_middleware_stub())
    stubs.update(_make_security_stub())
    stubs.update(_make_graph_stubs(direct_entry_path=direct_entry_path))
    stubs.update(_make_agents_stub())
    if extra_stubs:
        stubs.update(extra_stubs)

    saved: dict[str, Any] = {name: sys.modules.get(name) for name in stubs}

    sys.path.insert(0, str(tmp_path))
    for name, mod in stubs.items():
        sys.modules[name] = mod

    # Purge any prior backend.* import so the fresh render is always used.
    for key in list(sys.modules.keys()):
        if key == "backend" or key.startswith("backend."):
            del sys.modules[key]

    try:
        main_mod = importlib.import_module("backend.main")
        app = main_mod.app
        with TestClient(app, raise_server_exceptions=True) as client:
            yield client
    finally:
        sys.path.remove(str(tmp_path))
        for name, orig in saved.items():
            if orig is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = orig
        for key in list(sys.modules.keys()):
            if key == "backend" or key.startswith("backend."):
                del sys.modules[key]


def test_testclient_intent_router_returns_200(tmp_path: Path) -> None:
    """Rendered intent_router main.py must respond 200 to a POST /query with a valid body."""
    with _scaffold_client_context(tmp_path, "intent_router") as client:
        response = client.post("/query", json={"query": "What is the top revenue?"})

    assert response.status_code == 200, (
        f"Expected 200 from intent_router /query, got {response.status_code}: {response.text}"
    )
    data = response.json()
    assert "success" in data, "Response must have 'success' field"
    assert "answer" in data, "Response must have 'answer' field"
    assert "error" in data, "Response must have 'error' field"
    assert "trace_id" in data, "Response must have 'trace_id' field"
    assert data["success"] is True, f"Expected success=True, got {data['success']}"


def test_testclient_passthrough_returns_200(tmp_path: Path) -> None:
    """Rendered passthrough main.py must respond 200 to a POST /query with intent+query body."""
    # passthrough_node is imported lazily inside the endpoint; stub it so the
    # await call succeeds without a real LangChain/OpenAI dependency.
    async def _fake_passthrough_node(state: dict) -> dict:  # noqa: WPS430
        return {**state, "inputs": {"extracted": True}}

    graph_nodes_pkg = types.ModuleType("graph.nodes")
    graph_nodes_pt = types.ModuleType("graph.nodes.passthrough_node")
    graph_nodes_pt.passthrough_node = _fake_passthrough_node  # type: ignore[attr-defined]
    graph_nodes_pkg.passthrough_node = graph_nodes_pt  # type: ignore[attr-defined]

    extra = {
        "graph.nodes": graph_nodes_pkg,
        "graph.nodes.passthrough_node": graph_nodes_pt,
    }

    with _scaffold_client_context(tmp_path, "passthrough", extra_stubs=extra) as client:
        response = client.post(
            "/query", json={"intent": "sql", "query": "Show me revenue by quarter"}
        )

    assert response.status_code == 200, (
        f"Expected 200 from passthrough /query, got {response.status_code}: {response.text}"
    )
    data = response.json()
    assert "success" in data, "Response must have 'success' field"
    assert "answer" in data, "Response must have 'answer' field"
    assert data["success"] is True, f"Expected success=True, got {data['success']}"


def test_testclient_direct_returns_200(tmp_path: Path) -> None:
    """Rendered direct main.py must respond 200 to a POST /query with intent+inputs body."""
    with _scaffold_client_context(tmp_path, "direct") as client:
        response = client.post(
            "/query", json={"intent": "sql", "inputs": {"table": "orders"}}
        )

    assert response.status_code == 200, (
        f"Expected 200 from direct /query, got {response.status_code}: {response.text}"
    )
    data = response.json()
    assert "success" in data, "Response must have 'success' field"
    assert "answer" in data, "Response must have 'answer' field"
    assert data["success"] is True, f"Expected success=True, got {data['success']}"
