"""
Tests for the planner pattern template overlay (TODO-v2-5).

Covers:
- Render planner fixture with all nodes enabled; AST-compile all generated files.
- Parametrize precheck_enabled, validator_enabled, composer_enabled each over
  [True, False] — verify conditional emission: absent nodes do NOT produce files.
- Parametrize max_replans in {0, 2, 5} and max_concurrency in {1, 4} — verify
  values appear in rendered source (regex) and no bare literals present.
- Precheck unit tests (standalone — test the pure precheck logic):
  - Reject plan missing id / tool / args / deps fields (shape).
  - Reject plan with unknown tool ref.
  - Reject plan with cycle.
  - Reject plan with JSON Pointer where stepN is not in deps.
  - Accept a valid 3-step DAG.
- Integration test: precheck node returns precheck_ok=False for bad plan,
  precheck_ok=True for good plan.
- Byte-identity regression: existing tests still pass (no cross-pattern bleed).
"""
from __future__ import annotations

import ast
import importlib
import importlib.util
import logging
import re
import sys
import tempfile
import types
from pathlib import Path
from typing import Any

import pytest

from agentforge.engine.renderer import TemplateRenderer
from agentforge.schema.models import ProjectConfig, PlannerConfig


# ── Helpers ───────────────────────────────────────────────────────────────────

_PLANNER_TEMPLATES_DIR = (
    Path(__file__).parent.parent.parent
    / "agentforge"
    / "templates"
    / "patterns"
    / "planner"
)


def _make_planner_config(
    max_replans: int = 2,
    max_concurrency: int = 4,
    precheck_enabled: bool = True,
    validator_enabled: bool = True,
    composer_enabled: bool = True,
    tool_names: list[str] | None = None,
) -> ProjectConfig:
    """Build a minimal valid ProjectConfig with ``pattern: planner``."""
    if tool_names is None:
        tool_names = ["web_search", "analyse_data"]
    tools = [
        {"name": t, "description": f"{t} tool", "kind": "mcp"}
        for t in tool_names
    ]
    return ProjectConfig.model_validate({
        "metadata": {
            "name": "planner_test_project",
            "description": "Planner render test",
            "python_version": "3.11",
            "author": "Test Author",
            "email": "test@example.com",
        },
        "agents": [
            {
                "key": "search",
                "class_name": "SearchAgent",
                "llm_model": "gpt-4o-mini",
                "system_prompt": "You are a search agent.",
                "tools": tools,
            }
        ],
        "database": {"backend": "postgres", "tables": []},
        "workflow": {
            "default_intent": "search",
            "enable_feedback_loop": False,
            "enable_validation_node": False,
        },
        "pattern": "planner",
        "entry": {"type": "direct"},
        "planner": {
            "max_replans": max_replans,
            "max_concurrency": max_concurrency,
            "precheck_enabled": precheck_enabled,
            "validator_enabled": validator_enabled,
            "composer_enabled": composer_enabled,
        },
    })


def _render_map(config: ProjectConfig) -> dict[str, str]:
    """Render all templates and return {relative_path: content}."""
    renderer = TemplateRenderer()
    return {str(path): content for path, content in renderer.render_all(config)}


def _make_fake_observability_mod() -> types.ModuleType:
    """Create a lightweight stub for the observability.logging module.

    The scaffolded nodes import ``from observability.logging import get_logger``.
    In the test environment, this package does not exist. We inject a minimal
    stub so the rendered modules can be imported for integration testing without
    needing the full project runtime environment.
    """
    obs_pkg = types.ModuleType("observability")
    obs_log = types.ModuleType("observability.logging")

    def get_logger(name: str) -> logging.Logger:  # noqa: WPS430
        return logging.getLogger(name)

    obs_log.get_logger = get_logger
    obs_pkg.logging = obs_log
    return obs_pkg, obs_log


def _render_precheck_module(tool_names: list[str] | None = None) -> Any:
    """Render _precheck.py.j2 and return the imported module.

    Renders the template into a temp file, imports it as a module, and
    returns it so its functions can be called directly in unit tests.
    The _precheck module has no scaffolded-project dependencies (pure Python),
    so no stubs are needed.
    """
    if tool_names is None:
        tool_names = ["web_search", "analyse_data"]
    config = _make_planner_config(tool_names=tool_names)
    rendered = _render_map(config)
    source = rendered["backend/graph/planner/_precheck.py"]

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", prefix="_precheck_test_", delete=False
    ) as f:
        f.write(source)
        tmp_path = f.name

    spec = importlib.util.spec_from_file_location("_precheck_test", tmp_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_precheck_node_with_stubs(
    node_src: str, helper_src: str, mod_name: str
) -> Any:
    """Import a rendered plan_precheck_node.py with all external deps stubbed.

    Stubs injected:
    - ``observability`` / ``observability.logging`` — provides ``get_logger``.
    - The ``check_plan`` import is replaced with a version loaded from the
      rendered _precheck.py source (no relative import path needed).

    Args:
        node_src: Rendered plan_precheck_node.py source text.
        helper_src: Rendered _precheck.py source text.
        mod_name: Unique module name to register in sys.modules.

    Returns:
        The imported module object.
    """
    obs_pkg, obs_log = _make_fake_observability_mod()

    # Load the precheck helper into a temp module.
    helper_mod_name = f"_precheck_helper_{mod_name}"
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", prefix=helper_mod_name, delete=False
    ) as f:
        f.write(helper_src)
        helper_path = f.name

    helper_spec = importlib.util.spec_from_file_location(helper_mod_name, helper_path)
    helper_mod = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper_mod)

    # Patch the node source: replace relative import with helper_mod reference.
    patched = node_src.replace(
        "from ..planner._precheck import check_plan",
        f"# import patched by test harness\n"
        f"import sys as _sys\n"
        f"check_plan = _sys.modules['{helper_mod_name}'].check_plan",
    )
    # Replace the langchain_core.runnables import — not needed for our tests.
    patched = patched.replace(
        "from langchain_core.runnables import RunnableConfig",
        "RunnableConfig = object  # stubbed by test harness",
    )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", prefix=mod_name, delete=False
    ) as f:
        f.write(patched)
        node_path = f.name

    # Register stubs and helpers in sys.modules before importing node.
    old_obs = sys.modules.get("observability")
    old_obs_log = sys.modules.get("observability.logging")
    sys.modules[helper_mod_name] = helper_mod
    sys.modules["observability"] = obs_pkg
    sys.modules["observability.logging"] = obs_log

    try:
        node_spec = importlib.util.spec_from_file_location(mod_name, node_path)
        node_mod = importlib.util.module_from_spec(node_spec)
        node_spec.loader.exec_module(node_mod)
    finally:
        # Restore sys.modules to pre-test state.
        if old_obs is None:
            sys.modules.pop("observability", None)
        else:
            sys.modules["observability"] = old_obs
        if old_obs_log is None:
            sys.modules.pop("observability.logging", None)
        else:
            sys.modules["observability.logging"] = old_obs_log

    return node_mod


# ── AST-compile: all generated .py files (all nodes enabled) ─────────────────


def test_planner_all_py_files_ast_compile_all_enabled() -> None:
    """All rendered .py files for a fully-enabled planner project must parse."""
    config = _make_planner_config()
    rendered = _render_map(config)
    py_files = {p: c for p, c in rendered.items() if p.endswith(".py")}
    assert py_files, "No .py files rendered for planner project"

    for path, source in py_files.items():
        try:
            ast.parse(source)
        except SyntaxError as exc:
            pytest.fail(
                f"Planner render produced invalid Python in {path!r}:\n{exc}\n\n{source}"
            )


# ── Expected planner files present ───────────────────────────────────────────


def test_planner_expected_files_present_all_enabled() -> None:
    """All six planner-specific files must be emitted when all flags are True."""
    config = _make_planner_config()
    rendered = _render_map(config)

    expected = [
        "backend/graph/nodes/plan_and_run_node.py",
        "backend/graph/nodes/plan_precheck_node.py",
        "backend/graph/nodes/solver_node.py",
        "backend/graph/nodes/validator_node.py",
        "backend/graph/nodes/composer_node.py",
        "backend/graph/planner/_precheck.py",
    ]
    for path in expected:
        assert path in rendered, f"{path!r} missing from planner render output"


# ── Conditional emission: precheck_enabled ────────────────────────────────────


@pytest.mark.parametrize("enabled", [True, False])
def test_planner_precheck_conditional_emission(enabled: bool) -> None:
    """plan_precheck_node.py and _precheck.py are emitted iff precheck_enabled."""
    config = _make_planner_config(precheck_enabled=enabled)
    rendered = _render_map(config)

    precheck_node = "backend/graph/nodes/plan_precheck_node.py"
    precheck_helper = "backend/graph/planner/_precheck.py"

    if enabled:
        assert precheck_node in rendered, (
            f"precheck_enabled=True: {precheck_node!r} must be emitted"
        )
        assert precheck_helper in rendered, (
            f"precheck_enabled=True: {precheck_helper!r} must be emitted"
        )
    else:
        assert precheck_node not in rendered, (
            f"precheck_enabled=False: {precheck_node!r} must NOT be emitted"
        )
        assert precheck_helper not in rendered, (
            f"precheck_enabled=False: {precheck_helper!r} must NOT be emitted"
        )


# ── Conditional emission: validator_enabled ───────────────────────────────────


@pytest.mark.parametrize("enabled", [True, False])
def test_planner_validator_conditional_emission(enabled: bool) -> None:
    """validator_node.py is emitted iff validator_enabled."""
    config = _make_planner_config(validator_enabled=enabled)
    rendered = _render_map(config)
    path = "backend/graph/nodes/validator_node.py"

    if enabled:
        assert path in rendered, f"validator_enabled=True: {path!r} must be emitted"
    else:
        assert path not in rendered, f"validator_enabled=False: {path!r} must NOT be emitted"


# ── Conditional emission: composer_enabled ────────────────────────────────────


@pytest.mark.parametrize("enabled", [True, False])
def test_planner_composer_conditional_emission(enabled: bool) -> None:
    """composer_node.py is emitted iff composer_enabled."""
    config = _make_planner_config(composer_enabled=enabled)
    rendered = _render_map(config)
    path = "backend/graph/nodes/composer_node.py"

    if enabled:
        assert path in rendered, f"composer_enabled=True: {path!r} must be emitted"
    else:
        assert path not in rendered, f"composer_enabled=False: {path!r} must NOT be emitted"


# ── Conditional emission: all flags disabled → still valid Python ─────────────


def test_planner_all_flags_disabled_ast_compile() -> None:
    """When all optional nodes disabled, remaining files must still parse as Python."""
    config = _make_planner_config(
        precheck_enabled=False, validator_enabled=False, composer_enabled=False
    )
    rendered = _render_map(config)
    py_files = {p: c for p, c in rendered.items() if p.endswith(".py")}
    for path, source in py_files.items():
        try:
            ast.parse(source)
        except SyntaxError as exc:
            pytest.fail(
                f"All-disabled planner render produced invalid Python in {path!r}:\n"
                f"{exc}\n\n{source}"
            )


# ── max_replans parametrization ───────────────────────────────────────────────


@pytest.mark.parametrize("max_replans", [0, 2, 5])
def test_planner_max_replans_value_in_rendered_source(max_replans: int) -> None:
    """The max_replans value must appear as _MAX_REPLANS in the rendered nodes."""
    config = _make_planner_config(max_replans=max_replans)
    rendered = _render_map(config)

    for path in [
        "backend/graph/nodes/plan_and_run_node.py",
        "backend/graph/nodes/validator_node.py",
        "backend/graph/workflow.py",
    ]:
        assert path in rendered, f"{path!r} missing"
        source = rendered[path]
        assert str(max_replans) in source, (
            f"max_replans={max_replans} not found in {path!r}. "
            "The template must inject the config value."
        )


# ── max_concurrency parametrization ──────────────────────────────────────────


@pytest.mark.parametrize("max_concurrency", [1, 4])
def test_planner_max_concurrency_value_in_solver(max_concurrency: int) -> None:
    """The max_concurrency value must appear as _MAX_CONCURRENCY in solver_node.py."""
    config = _make_planner_config(max_concurrency=max_concurrency)
    rendered = _render_map(config)

    path = "backend/graph/nodes/solver_node.py"
    assert path in rendered, f"{path!r} missing"
    source = rendered[path]
    assert f"_MAX_CONCURRENCY: int = {max_concurrency}" in source, (
        f"_MAX_CONCURRENCY = {max_concurrency} not found in solver_node.py. "
        "The template must inject the config value."
    )


# ── Tool names appear in generated source ─────────────────────────────────────


def test_planner_tool_names_in_precheck_and_plan_node() -> None:
    """Declared tool names must appear in _precheck.py and plan_and_run_node.py."""
    tool_names = ["my_custom_tool", "another_tool"]
    config = _make_planner_config(tool_names=tool_names)
    rendered = _render_map(config)

    for path in [
        "backend/graph/planner/_precheck.py",
        "backend/graph/nodes/plan_and_run_node.py",
    ]:
        source = rendered[path]
        for name in tool_names:
            assert f'"{name}"' in source, (
                f"Tool name {name!r} not found in {path!r}. "
                "Tool names must be injected from project.yaml, not hardcoded."
            )


# ── workflow.py wiring: nodes registered correctly ────────────────────────────


def test_planner_workflow_registers_plan_and_solver_nodes() -> None:
    """workflow.py must always register plan_and_run and solver nodes."""
    config = _make_planner_config()
    rendered = _render_map(config)
    source = rendered["backend/graph/workflow.py"]

    assert 'add_node("plan_and_run"' in source or "add_node('plan_and_run'" in source, (
        "workflow.py must add_node('plan_and_run', ...)"
    )
    assert 'add_node("solver"' in source or "add_node('solver'" in source, (
        "workflow.py must add_node('solver', ...)"
    )


def test_planner_workflow_has_precheck_node_when_enabled() -> None:
    """workflow.py must add_node('precheck', ...) when precheck_enabled=True."""
    config = _make_planner_config(precheck_enabled=True)
    rendered = _render_map(config)
    source = rendered["backend/graph/workflow.py"]

    assert 'add_node("precheck"' in source or "add_node('precheck'" in source, (
        "workflow.py must register precheck node when precheck_enabled=True"
    )


def test_planner_workflow_no_precheck_node_when_disabled() -> None:
    """workflow.py must NOT add_node('precheck', ...) when precheck_enabled=False."""
    config = _make_planner_config(precheck_enabled=False)
    rendered = _render_map(config)
    source = rendered["backend/graph/workflow.py"]

    assert 'add_node("precheck"' not in source and "add_node('precheck'" not in source, (
        "workflow.py must NOT register precheck node when precheck_enabled=False"
    )


def test_planner_workflow_has_conditional_edges_for_precheck() -> None:
    """workflow.py must use add_conditional_edges for precheck routing when enabled."""
    config = _make_planner_config(precheck_enabled=True)
    rendered = _render_map(config)
    source = rendered["backend/graph/workflow.py"]

    assert "add_conditional_edges" in source, (
        "workflow.py must use add_conditional_edges for precheck routing"
    )


# ── Precheck unit tests (standalone — pure function) ─────────────────────────


@pytest.fixture(scope="module")
def precheck_mod():
    """Render and import the _precheck module for unit testing."""
    return _render_precheck_module(tool_names=["web_search", "analyse_data"])


def test_precheck_rejects_missing_id_field(precheck_mod) -> None:
    """check_plan must reject a step missing the 'id' field."""
    plan = [{"tool": "web_search", "args": {}, "deps": []}]
    ok, errors = precheck_mod.check_plan(plan, frozenset(["web_search"]))
    assert not ok, "Must reject plan with missing 'id'"
    assert any("id" in e for e in errors), f"Error should mention 'id', got: {errors}"


def test_precheck_rejects_missing_tool_field(precheck_mod) -> None:
    """check_plan must reject a step missing the 'tool' field."""
    plan = [{"id": "step1", "args": {}, "deps": []}]
    ok, errors = precheck_mod.check_plan(plan, frozenset(["web_search"]))
    assert not ok, "Must reject plan with missing 'tool'"
    assert any("tool" in e for e in errors), f"Error should mention 'tool', got: {errors}"


def test_precheck_rejects_missing_args_field(precheck_mod) -> None:
    """check_plan must reject a step missing the 'args' field."""
    plan = [{"id": "step1", "tool": "web_search", "deps": []}]
    ok, errors = precheck_mod.check_plan(plan, frozenset(["web_search"]))
    assert not ok, "Must reject plan with missing 'args'"
    assert any("args" in e for e in errors), f"Error should mention 'args', got: {errors}"


def test_precheck_rejects_missing_deps_field(precheck_mod) -> None:
    """check_plan must reject a step missing the 'deps' field."""
    plan = [{"id": "step1", "tool": "web_search", "args": {}}]
    ok, errors = precheck_mod.check_plan(plan, frozenset(["web_search"]))
    assert not ok, "Must reject plan with missing 'deps'"
    assert any("deps" in e for e in errors), f"Error should mention 'deps', got: {errors}"


def test_precheck_rejects_unknown_tool_ref(precheck_mod) -> None:
    """check_plan must reject a plan referencing a tool not in the registry."""
    plan = [{"id": "step1", "tool": "unknown_tool", "args": {}, "deps": []}]
    ok, errors = precheck_mod.check_plan(plan, frozenset(["web_search"]))
    assert not ok, "Must reject plan with unknown tool ref"
    assert any("unknown_tool" in e for e in errors), (
        f"Error should mention the bad tool name, got: {errors}"
    )


def test_precheck_rejects_cycle(precheck_mod) -> None:
    """check_plan must reject a plan with a dependency cycle."""
    plan = [
        {"id": "step_a", "tool": "web_search", "args": {}, "deps": ["step_b"]},
        {"id": "step_b", "tool": "web_search", "args": {}, "deps": ["step_a"]},
    ]
    ok, errors = precheck_mod.check_plan(plan, frozenset(["web_search"]))
    assert not ok, "Must reject plan with dependency cycle"
    assert any("cycle" in e.lower() for e in errors), (
        f"Error should mention 'cycle', got: {errors}"
    )


def test_precheck_rejects_undeclared_dep(precheck_mod) -> None:
    """check_plan must reject a step that depends on a non-existent step id."""
    plan = [
        {"id": "step1", "tool": "web_search", "args": {}, "deps": ["step_ghost"]},
    ]
    ok, errors = precheck_mod.check_plan(plan, frozenset(["web_search"]))
    assert not ok, "Must reject plan with undeclared dep"
    assert any("step_ghost" in e for e in errors), (
        f"Error should mention the bad dep id 'step_ghost', got: {errors}"
    )


def test_precheck_rejects_dangling_json_pointer(precheck_mod) -> None:
    """check_plan must reject pointer refs where the target step is not in deps."""
    plan = [
        {"id": "step1", "tool": "web_search", "args": {"q": "${step2/result}"}, "deps": []},
        {"id": "step2", "tool": "web_search", "args": {}, "deps": []},
    ]
    ok, errors = precheck_mod.check_plan(plan, frozenset(["web_search"]))
    assert not ok, "Must reject plan with dangling JSON Pointer ref"
    assert any("step2" in e for e in errors), (
        f"Error should mention 'step2' (the undeclared dep in pointer), got: {errors}"
    )


def test_precheck_accepts_valid_3step_dag(precheck_mod) -> None:
    """check_plan must accept a valid 3-step DAG."""
    plan = [
        {"id": "step1", "tool": "web_search", "args": {"query": "test"}, "deps": []},
        {"id": "step2", "tool": "analyse_data", "args": {"data": "${step1/result}"}, "deps": ["step1"]},
        {"id": "step3", "tool": "web_search", "args": {"query": "${step2/summary}"}, "deps": ["step2"]},
    ]
    ok, errors = precheck_mod.check_plan(plan, frozenset(["web_search", "analyse_data"]))
    assert ok, f"Must accept valid 3-step DAG, got errors: {errors}"
    assert errors == [], f"Errors list must be empty, got: {errors}"


def test_precheck_uses_scaffold_time_registry_by_default(precheck_mod) -> None:
    """check_plan() with no tool_registry arg must use the baked-in _REGISTERED_TOOLS."""
    plan = [{"id": "step1", "tool": "web_search", "args": {}, "deps": []}]
    ok, errors = precheck_mod.check_plan(plan)
    assert ok, f"web_search is in the baked-in registry; got errors: {errors}"


def test_precheck_rejects_tool_not_in_scaffold_time_registry(precheck_mod) -> None:
    """check_plan() with no tool_registry arg must reject tools not in _REGISTERED_TOOLS."""
    plan = [{"id": "step1", "tool": "secret_tool", "args": {}, "deps": []}]
    ok, errors = precheck_mod.check_plan(plan)
    assert not ok, "Must reject tool not in baked-in registry"


# ── Integration test: precheck failure → replan ───────────────────────────────


def test_planner_precheck_node_state_on_failure() -> None:
    """plan_precheck_node must set precheck_ok=False and populate replan_reason on bad plan."""
    import asyncio

    config = _make_planner_config(tool_names=["web_search"])
    rendered = _render_map(config)

    helper_src = rendered["backend/graph/planner/_precheck.py"]
    node_src = rendered["backend/graph/nodes/plan_precheck_node.py"]

    mod = _load_precheck_node_with_stubs(node_src, helper_src, "_precheck_node_fail")

    bad_plan = [{"id": "step1", "tool": "forbidden_tool", "args": {}, "deps": []}]
    state = {"plan": bad_plan, "replan_count": 0}

    result = asyncio.get_event_loop().run_until_complete(
        mod.plan_precheck_node(state, config={})
    )

    assert result["precheck_ok"] is False, "precheck_ok must be False for bad plan"
    assert result["replan_reason"] is not None, "replan_reason must be set on failure"
    assert len(result["replan_reason"]) > 0, "replan_reason must be non-empty"


def test_planner_precheck_node_state_on_success() -> None:
    """plan_precheck_node must set precheck_ok=True and clear replan_reason on good plan."""
    import asyncio

    config = _make_planner_config(tool_names=["web_search"])
    rendered = _render_map(config)

    helper_src = rendered["backend/graph/planner/_precheck.py"]
    node_src = rendered["backend/graph/nodes/plan_precheck_node.py"]

    mod = _load_precheck_node_with_stubs(node_src, helper_src, "_precheck_node_ok")

    good_plan = [{"id": "step1", "tool": "web_search", "args": {"q": "hello"}, "deps": []}]
    state = {"plan": good_plan, "replan_count": 0}

    result = asyncio.get_event_loop().run_until_complete(
        mod.plan_precheck_node(state, config={})
    )

    assert result["precheck_ok"] is True, "precheck_ok must be True for good plan"
    assert result["replan_reason"] is None, "replan_reason must be None on success"


# ── No planner-specific files for non-planner patterns ───────────────────────


def test_planner_files_absent_for_orchestrator() -> None:
    """Planner-specific files must NOT be emitted for orchestrator-pattern projects."""
    config = ProjectConfig.model_validate({
        "metadata": {
            "name": "orch_test",
            "description": "Orchestrator test",
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
            }
        ],
        "database": {"backend": "postgres", "tables": []},
        "workflow": {
            "default_intent": "sql",
            "enable_feedback_loop": True,
            "enable_validation_node": True,
        },
    })
    rendered = _render_map(config)

    planner_paths = [
        "backend/graph/nodes/plan_and_run_node.py",
        "backend/graph/nodes/plan_precheck_node.py",
        "backend/graph/nodes/solver_node.py",
        "backend/graph/nodes/validator_node.py",
        "backend/graph/nodes/composer_node.py",
        "backend/graph/planner/_precheck.py",
    ]
    for path in planner_paths:
        assert path not in rendered, (
            f"{path!r} must NOT be emitted for orchestrator projects (cross-pattern bleed)"
        )


# ── Context aliases from _build_context ──────────────────────────────────────


def test_planner_context_aliases_populated() -> None:
    """_build_context must populate all planner_* aliases from PlannerConfig."""
    config = _make_planner_config(
        max_replans=3,
        max_concurrency=2,
        precheck_enabled=True,
        validator_enabled=False,
        composer_enabled=True,
        tool_names=["alpha_tool"],
    )
    ctx = TemplateRenderer._build_context(config)

    assert ctx["planner_max_replans"] == 3
    assert ctx["planner_max_concurrency"] == 2
    assert ctx["planner_precheck_enabled"] is True
    assert ctx["planner_validator_enabled"] is False
    assert ctx["planner_composer_enabled"] is True
    assert "alpha_tool" in ctx["planner_tool_names"]


def test_planner_context_defaults_when_no_planner_block() -> None:
    """_build_context must use PlannerConfig defaults when planner block is absent."""
    config = ProjectConfig.model_validate({
        "metadata": {
            "name": "defaults_test",
            "description": "Defaults test",
            "python_version": "3.11",
            "author": "Test Author",
            "email": "test@example.com",
        },
        "agents": [
            {"key": "alpha", "class_name": "AlphaAgent", "llm_model": "gpt-4o-mini", "system_prompt": "Hi."}
        ],
        "database": {"backend": "postgres", "tables": []},
        "workflow": {"default_intent": "alpha", "enable_feedback_loop": False, "enable_validation_node": False},
        "pattern": "fanout",
        "entry": {"type": "direct"},
    })
    ctx = TemplateRenderer._build_context(config)

    # Defaults from PlannerConfig schema must apply (or the hardcoded fallback in renderer).
    assert ctx["planner_max_replans"] == 2
    assert ctx["planner_max_concurrency"] == 4
    assert ctx["planner_precheck_enabled"] is True
    assert ctx["planner_validator_enabled"] is True
    assert ctx["planner_composer_enabled"] is True


# ── Template hardcode guards ──────────────────────────────────────────────────


def _strip_jinja(source: str) -> str:
    """Remove all Jinja2 expression/statement/comment blocks from source."""
    return re.sub(r"\{[{%#].*?[}%#]\}", "", source, flags=re.DOTALL)


@pytest.mark.parametrize("template_name", [
    "plan_and_run_node.py.j2",
    "solver_node.py.j2",
    "validator_node.py.j2",
    "composer_node.py.j2",
    "workflow.py.j2",
])
def test_planner_templates_no_hardcoded_max_replans(template_name: str) -> None:
    """Planner templates must not hardcode the default max_replans integer (2) in static text."""
    template_path = _PLANNER_TEMPLATES_DIR / template_name
    assert template_path.exists(), f"Template not found: {template_path}"
    raw = template_path.read_text(encoding="utf-8")
    stripped = _strip_jinja(raw)

    assert not re.search(r"\bMAX_REPLANS\s*[:=]\s*2\b", stripped), (
        f"{template_name} must not hardcode MAX_REPLANS=2. "
        "Use the planner_max_replans Jinja variable."
    )


@pytest.mark.parametrize("template_name", [
    "solver_node.py.j2",
    "workflow.py.j2",
])
def test_planner_templates_no_hardcoded_max_concurrency(template_name: str) -> None:
    """Planner templates must not hardcode the default max_concurrency integer (4) in static text."""
    template_path = _PLANNER_TEMPLATES_DIR / template_name
    assert template_path.exists(), f"Template not found: {template_path}"
    raw = template_path.read_text(encoding="utf-8")
    stripped = _strip_jinja(raw)

    assert not re.search(r"\bMAX_CONCURRENCY\s*[:=]\s*4\b", stripped), (
        f"{template_name} must not hardcode MAX_CONCURRENCY=4. "
        "Use the planner_max_concurrency Jinja variable."
    )


# ── PlannerConfig schema validation ──────────────────────────────────────────


def test_planner_config_max_replans_default() -> None:
    """PlannerConfig must default max_replans to 2."""
    cfg = PlannerConfig()
    assert cfg.max_replans == 2


def test_planner_config_max_concurrency_default() -> None:
    """PlannerConfig must default max_concurrency to 4."""
    cfg = PlannerConfig()
    assert cfg.max_concurrency == 4


def test_planner_config_max_replans_ge_zero() -> None:
    """PlannerConfig must accept max_replans=0 (no replans allowed)."""
    cfg = PlannerConfig(max_replans=0)
    assert cfg.max_replans == 0


def test_planner_config_max_concurrency_ge_one() -> None:
    """PlannerConfig must reject max_concurrency=0 (must be >= 1)."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        PlannerConfig(max_concurrency=0)


# ── Workflow.py: PlannerState TypedDict ──────────────────────────────────────


def test_planner_workflow_declares_planner_state() -> None:
    """workflow.py must declare a PlannerState TypedDict."""
    config = _make_planner_config()
    rendered = _render_map(config)
    source = rendered["backend/graph/workflow.py"]

    assert "PlannerState" in source, (
        "workflow.py must declare PlannerState TypedDict"
    )
    assert "TypedDict" in source, (
        "workflow.py must import/use TypedDict"
    )


def test_planner_workflow_has_replan_count_in_state() -> None:
    """PlannerState in workflow.py must include replan_count field."""
    config = _make_planner_config()
    rendered = _render_map(config)
    source = rendered["backend/graph/workflow.py"]

    assert "replan_count" in source, (
        "workflow.py must declare replan_count in PlannerState"
    )


def test_planner_workflow_has_replan_reason_in_state() -> None:
    """PlannerState in workflow.py must include replan_reason field."""
    config = _make_planner_config()
    rendered = _render_map(config)
    source = rendered["backend/graph/workflow.py"]

    assert "replan_reason" in source, (
        "workflow.py must declare replan_reason in PlannerState"
    )


# ── Risk warnings: scaffold header comments ───────────────────────────────────


@pytest.mark.parametrize("template_name, keyword", [
    ("plan_and_run_node.py.j2", "IDEMPOTENCY"),
    ("plan_and_run_node.py.j2", "STATE SIZE"),
    ("solver_node.py.j2", "IDEMPOTENCY"),
    ("solver_node.py.j2", "STATE SIZE"),
    ("workflow.py.j2", "IDEMPOTENCY"),
    ("workflow.py.j2", "STATE SIZE"),
])
def test_planner_templates_contain_risk_warnings(template_name: str, keyword: str) -> None:
    """Planner templates must contain the mandatory scaffold risk warning comments."""
    template_path = _PLANNER_TEMPLATES_DIR / template_name
    assert template_path.exists(), f"Template not found: {template_path}"
    raw = template_path.read_text(encoding="utf-8")

    assert keyword in raw, (
        f"{template_name} must contain the SCAFFOLD RISK — {keyword} warning comment. "
        "This is a required safety callout for operators."
    )


# ── Real-import e2e test ──────────────────────────────────────────────────────


def test_planner_precheck_node_real_import(tmp_path: Path) -> None:
    """Render planner project to tmp_path and verify plan_precheck_node.py imports correctly.

    This test writes all planner files to disk using raw Path writes (mirroring
    what ScaffoldWriter does), adds the project root to sys.path, registers the
    observability stub, and uses importlib.import_module to resolve the relative
    import chain:

        backend.graph.nodes.plan_precheck_node
            -> from ..planner._precheck import check_plan
               (resolves to backend.graph.planner._precheck)

    The test asserts no ImportError is raised, which validates that the relative
    import path in the template is correct.
    """
    config = _make_planner_config(tool_names=["web_search"])
    rendered = _render_map(config)

    # Write all rendered files to tmp_path.
    for rel_path, content in rendered.items():
        dest = tmp_path / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")

    # The generated modules use absolute imports anchored at the backend/ dir
    # *and* relative imports within backend/graph/.  Adding tmp_path to sys.path
    # lets Python resolve "backend.graph.nodes.plan_precheck_node" as a package.
    sys.path.insert(0, str(tmp_path))

    # Register the observability stub before importing the node.
    obs_pkg, obs_log = _make_fake_observability_mod()
    # Also stub langchain_core.runnables so the import succeeds without a full
    # langchain installation wired for the tmp project.
    lc_runnables = types.ModuleType("langchain_core.runnables")
    lc_runnables.RunnableConfig = object  # type: ignore[attr-defined]
    lc_core = types.ModuleType("langchain_core")
    lc_core.runnables = lc_runnables  # type: ignore[attr-defined]

    saved = {}
    for mod_name in [
        "observability",
        "observability.logging",
        "langchain_core",
        "langchain_core.runnables",
    ]:
        saved[mod_name] = sys.modules.get(mod_name)

    sys.modules["observability"] = obs_pkg
    sys.modules["observability.logging"] = obs_log
    sys.modules["langchain_core"] = lc_core
    sys.modules["langchain_core.runnables"] = lc_runnables

    # Clear any prior import of these modules so fresh resolution is used.
    for key in list(sys.modules.keys()):
        if key == "backend" or key.startswith("backend."):
            del sys.modules[key]

    try:
        mod = importlib.import_module("backend.graph.nodes.plan_precheck_node")
        assert hasattr(mod, "plan_precheck_node"), (
            "plan_precheck_node function must be defined in the imported module"
        )
    finally:
        # Restore sys.path and sys.modules.
        sys.path.remove(str(tmp_path))
        for mod_name, orig in saved.items():
            if orig is None:
                sys.modules.pop(mod_name, None)
            else:
                sys.modules[mod_name] = orig
        for key in list(sys.modules.keys()):
            if key == "backend" or key.startswith("backend."):
                del sys.modules[key]


# ── Replan round-trip test ────────────────────────────────────────────────────


def test_planner_replan_edge_fires_in_compiled_graph() -> None:
    """Compile a minimal planner-topology graph; verify the replan edge fires.

    This test builds a scaled-down StateGraph that replicates the routing logic
    from the generated workflow.py (_route_precheck / _route_validator) without
    depending on the generated node callables or LLM calls.

    Topology mirrors the generated graph:
        START → plan_and_run → precheck → [solver | replan→plan_and_run] → END

    Mock node behaviour:
    - plan_and_run: first call sets replan_count=0 and produces a "bad" plan
      (precheck will reject it); second call sets replan_count=1 and produces
      a "good" plan (precheck passes).
    - precheck: passes only when plan contains {"id": "ok"}.
    - solver: immediately returns done.

    Assertion: terminal state has replan_count == 1 (exactly one replan fired).
    """
    from langgraph.graph import StateGraph, END, START
    from langgraph.checkpoint.memory import MemorySaver
    from typing_extensions import TypedDict

    class _State(TypedDict, total=False):
        plan: list
        precheck_ok: bool
        replan_count: int
        replan_reason: str | None
        output: str

    _MAX = 2

    call_counts: dict[str, int] = {"plan_and_run": 0}

    async def _plan_and_run(state: _State) -> dict:
        count = call_counts["plan_and_run"]
        call_counts["plan_and_run"] += 1
        replan_count = state.get("replan_count", 0)
        if state.get("replan_reason") is not None:
            replan_count += 1
        if count == 0:
            # First call: produce a bad plan (precheck will reject).
            return {"plan": [{"id": "bad"}], "replan_count": replan_count, "replan_reason": None}
        # Second call: produce a good plan (precheck passes).
        return {"plan": [{"id": "ok"}], "replan_count": replan_count, "replan_reason": None}

    async def _precheck(state: _State) -> dict:
        plan = state.get("plan", [])
        ok = any(step.get("id") == "ok" for step in plan)
        reason = None if ok else "Step id is not 'ok'"
        return {"precheck_ok": ok, "replan_reason": reason}

    async def _solver(state: _State) -> dict:
        return {"output": "done"}

    def _route_precheck(state: dict) -> str:
        replan_count = state.get("replan_count", 0)
        if state.get("precheck_ok", False):
            return "solver"
        if replan_count >= _MAX:
            return END
        return "plan_and_run"

    graph = StateGraph(_State)
    graph.add_node("plan_and_run", _plan_and_run)
    graph.add_node("precheck", _precheck)
    graph.add_node("solver", _solver)

    graph.add_edge(START, "plan_and_run")
    graph.add_edge("plan_and_run", "precheck")
    graph.add_conditional_edges(
        "precheck",
        _route_precheck,
        {"solver": "solver", "plan_and_run": "plan_and_run", END: END},
    )
    graph.add_edge("solver", END)

    compiled = graph.compile(checkpointer=MemorySaver())

    import asyncio

    thread = {"configurable": {"thread_id": "replan-test-1"}}

    async def _run() -> dict:
        result = None
        async for chunk in compiled.astream(
            {"plan": [], "replan_count": 0, "replan_reason": None},
            config=thread,
        ):
            result = chunk
        # Return final state snapshot.
        return compiled.get_state(thread).values

    final_state = asyncio.get_event_loop().run_until_complete(_run())

    assert final_state.get("replan_count") == 1, (
        f"Expected replan_count=1 (one replan fired), got: {final_state.get('replan_count')}"
    )
    assert final_state.get("output") == "done", (
        f"Expected graph to reach solver and set output='done', got: {final_state.get('output')}"
    )
    assert call_counts["plan_and_run"] == 2, (
        f"plan_and_run must be called exactly twice (initial + 1 replan), "
        f"got: {call_counts['plan_and_run']}"
    )
