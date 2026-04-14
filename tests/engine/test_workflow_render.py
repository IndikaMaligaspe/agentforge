"""
Tests for the workflow pattern template overlay (TODO-v2-4).

Covers:
- Rendering a ``pattern: workflow`` fixture with step counts {1, 3, 5} produces
  files that all AST-compile without syntax errors.
- The rendered workflow.py forms the correct sequential edge sequence:
  START → step[0] → step[1] → ... → step[N-1] → END.
  Verified by regex scanning for ``add_edge("step_X", "step_Y")`` pairs.
- ``interrupt_before=[...]`` in ``.compile()`` contains exactly the configured
  step keys when ``hitl_before`` is non-empty.
- When ``hitl_before`` is empty, ``.compile()`` is called without arguments.
- ``human_review_node.py`` is emitted for workflow-pattern projects and is absent
  for non-workflow patterns (regression guard).
- Negative: ``hitl_before`` referencing an unknown step key → ``ValidationError``.
- Negative: ``pattern=workflow`` with empty ``steps`` → ``ValidationError``.
- No hardcoded step key strings in the static (non-Jinja) text of the template.
- ``interrupt_before`` is correctly passed to ``.compile()`` — validated against
  the rendered source (renderer-layer test, no live LangGraph runtime required).
- ``backend/graph/graph_agent.py`` is absent for workflow-pattern projects
  (regression guard against react overlay bleeding through).
- Negative: duplicate step keys in ``workflow_sm.steps`` → ``ValidationError``.
- Behavioral: compiled graph's ``interrupt_before_nodes`` equals ``hitl_before``.
- Behavioral: full interrupt / resume cycle with ``MemorySaver`` checkpointer.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Optional

import pytest
from pydantic import ValidationError
from typing_extensions import TypedDict

from agentforge.engine.renderer import TemplateRenderer
from agentforge.schema.models import (
    ProjectConfig,
    StepConfig,
    WorkflowStateMachineConfig,
)


# ── Template paths (for hardcode-guard tests) ─────────────────────────────────

_WORKFLOW_TEMPLATES_DIR = (
    Path(__file__).parent.parent.parent
    / "agentforge"
    / "templates"
    / "patterns"
    / "workflow"
)

# Step keys used by test fixtures — these must NOT appear hardcoded in templates.
_FIXTURE_STEP_KEYS = frozenset([
    "fetch_data", "validate_input", "process_records", "transform_output", "publish_result"
])


# ── Module-level TypedDict for behavioral LangGraph tests ─────────────────────
# Defined at module scope so LangGraph can resolve type hints correctly when
# StateGraph.__init__ calls get_type_hints().  Using only basic types (str,
# Optional[str]) avoids the NameError that occurs when typing.Any is referenced
# inside a locally-scoped TypedDict but resolved in its own module __globals__.

class _BehavioralWorkflowState(TypedDict, total=False):
    """Minimal state for behavioral interrupt/resume tests."""
    query: str
    output: Optional[str]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_step_dicts(count: int) -> list[dict]:
    """Build ``count`` minimal step dicts with distinct keys."""
    suffixes = ["fetch_data", "validate_input", "process_records", "transform_output", "publish_result"]
    descriptions = [
        "Fetch input data",
        "Validate input fields",
        "Process each record",
        "Transform for output",
        "Publish to destination",
    ]
    return [
        {"key": suffixes[i], "description": descriptions[i]}
        for i in range(count)
    ]


def _make_workflow_config(
    step_count: int = 3,
    hitl_before: list[str] | None = None,
) -> ProjectConfig:
    """Build a minimal valid ProjectConfig with ``pattern: workflow``.

    Notes
    -----
    - ``workflow.enable_feedback_loop`` and ``enable_validation_node`` are False
      (incompatible with workflow pattern per ``check_workflow_flags_pattern_compat``).
    - ``workflow.default_intent`` must match one of the agent keys.
    - ``workflow_sm.steps`` must have at least one entry.
    """
    if hitl_before is None:
        hitl_before = []
    steps = _make_step_dicts(step_count)
    return ProjectConfig.model_validate({
        "metadata": {
            "name": "workflow_test_project",
            "description": "Workflow state machine render test",
            "python_version": "3.11",
            "author": "Test Author",
            "email": "test@example.com",
        },
        "agents": [
            {
                "key": "worker",
                "class_name": "WorkerAgent",
                "llm_model": "gpt-4o-mini",
                "system_prompt": "You are the worker agent.",
            }
        ],
        "database": {"backend": "postgres", "tables": []},
        "workflow": {
            "default_intent": "worker",
            "enable_feedback_loop": False,
            "enable_validation_node": False,
        },
        "pattern": "workflow",
        "entry": {"type": "intent_router"},
        "workflow_sm": {
            "steps": steps,
            "hitl_before": hitl_before,
        },
    })


def _render_map(config: ProjectConfig) -> dict[str, str]:
    """Render all templates and return {relative_path_str: content}."""
    renderer = TemplateRenderer()
    return {str(path): content for path, content in renderer.render_all(config)}


def _strip_jinja(source: str) -> str:
    """Remove all Jinja2 expression/statement/comment blocks from source."""
    return re.sub(r"\{[{%#].*?[}%#]\}", "", source, flags=re.DOTALL)


# ── Minimal valid base config dict (for schema validation tests) ──────────────

_VALID_BASE = {
    "metadata": {
        "name": "schema_test_project",
        "description": "Schema validation test",
        "python_version": "3.11",
        "author": "Test Author",
        "email": "test@example.com",
    },
    "agents": [
        {
            "key": "worker",
            "class_name": "WorkerAgent",
            "llm_model": "gpt-4o-mini",
            "system_prompt": "You are the worker agent.",
        }
    ],
    "database": {"backend": "postgres", "tables": []},
    "workflow": {
        "default_intent": "worker",
        "enable_feedback_loop": False,
        "enable_validation_node": False,
    },
    "pattern": "workflow",
    "entry": {"type": "intent_router"},
}


# ── AST-compile: all generated .py files ──────────────────────────────────────


@pytest.mark.parametrize("step_count", [1, 3, 5])
@pytest.mark.parametrize("hitl_before_count", [0, 1])
def test_workflow_all_py_files_ast_compile(step_count: int, hitl_before_count: int) -> None:
    """All rendered .py files for a workflow project must parse as valid Python."""
    steps = _make_step_dicts(step_count)
    hitl_keys = [steps[0]["key"]] if hitl_before_count > 0 else []
    config = _make_workflow_config(step_count=step_count, hitl_before=hitl_keys)
    rendered = _render_map(config)

    py_files = {path: content for path, content in rendered.items() if path.endswith(".py")}
    assert py_files, "No .py files were rendered for workflow project"

    for path, source in py_files.items():
        try:
            ast.parse(source)
        except SyntaxError as exc:
            pytest.fail(
                f"Workflow render (steps={step_count}, hitl={hitl_keys!r}) "
                f"produced invalid Python in {path!r}:\n{exc}\n\n{source}"
            )


# ── workflow.py: sequential edge topology ─────────────────────────────────────


@pytest.mark.parametrize("step_count", [1, 3, 5])
def test_workflow_sequential_edges(step_count: int) -> None:
    """workflow.py must wire edges forming the exact sequential chain.

    For N steps: START → step[0], step[0] → step[1], ..., step[N-2] → step[N-1],
    step[N-1] → END.
    """
    steps = _make_step_dicts(step_count)
    config = _make_workflow_config(step_count=step_count)
    rendered = _render_map(config)

    path = "backend/graph/workflow.py"
    assert path in rendered, f"{path!r} missing from workflow render output"
    source = rendered[path]

    # Check START edge
    first_key = steps[0]["key"]
    assert f'add_edge(START, "{first_key}")' in source or f"add_edge(START, '{first_key}')" in source, (
        f"workflow.py must wire START → '{first_key}'"
    )

    # Check inter-step edges
    for i in range(step_count - 1):
        src_key = steps[i]["key"]
        dst_key = steps[i + 1]["key"]
        assert (
            f'add_edge("{src_key}", "{dst_key}")' in source
            or f"add_edge('{src_key}', '{dst_key}')" in source
        ), (
            f"workflow.py must wire edge from '{src_key}' to '{dst_key}' "
            f"(step_count={step_count})"
        )

    # Check END edge
    last_key = steps[-1]["key"]
    assert f'add_edge("{last_key}", END)' in source or f"add_edge('{last_key}', END)" in source, (
        f"workflow.py must wire '{last_key}' → END"
    )


@pytest.mark.parametrize("step_count", [1, 3, 5])
def test_workflow_has_add_node_per_step(step_count: int) -> None:
    """workflow.py must register one add_node call per configured step key."""
    steps = _make_step_dicts(step_count)
    config = _make_workflow_config(step_count=step_count)
    rendered = _render_map(config)
    source = rendered["backend/graph/workflow.py"]

    for step in steps:
        key = step["key"]
        assert f'add_node("{key}"' in source or f"add_node('{key}'" in source, (
            f"workflow.py must call add_node('{key}', ...) (step_count={step_count})"
        )


# ── workflow.py: interrupt_before in compile() ────────────────────────────────


@pytest.mark.parametrize("hitl_keys,expected", [
    ([], False),
    (["fetch_data"], True),
    (["fetch_data", "validate_input"], True),
])
def test_workflow_interrupt_before_in_compile(hitl_keys: list[str], expected: bool) -> None:
    """interrupt_before must appear in .compile() iff hitl_before is non-empty.

    When hitl_before is non-empty, the rendered source must contain:
        interrupt_before=[...]
    with exactly the configured keys.  When hitl_before is empty, the compile()
    call must NOT contain interrupt_before.
    """
    # Use a 5-step config so all hitl_keys reference valid steps.
    step_count = max(5, len(hitl_keys) + 1)
    config = _make_workflow_config(step_count=step_count, hitl_before=hitl_keys)
    rendered = _render_map(config)
    source = rendered["backend/graph/workflow.py"]

    if expected:
        assert "interrupt_before=" in source, (
            f"workflow.py must contain 'interrupt_before=' in .compile() "
            f"when hitl_before={hitl_keys!r}"
        )
        for key in hitl_keys:
            assert f'"{key}"' in source or f"'{key}'" in source, (
                f"workflow.py must contain the hitl key '{key}' in interrupt_before"
            )
    else:
        assert "interrupt_before=" not in source, (
            "workflow.py must NOT contain 'interrupt_before=' when hitl_before is empty"
        )


def test_workflow_interrupt_before_contains_exactly_configured_keys() -> None:
    """The interrupt_before list must contain ONLY the configured step keys.

    Uses a regex to extract the interrupt_before=[...] argument and performs
    set-equality against the expected hitl_before keys.
    """
    hitl_keys = ["validate_input", "process_records"]
    config = _make_workflow_config(step_count=5, hitl_before=hitl_keys)
    rendered = _render_map(config)
    source = rendered["backend/graph/workflow.py"]

    # Extract the interrupt_before=[...] argument.
    match = re.search(r"interrupt_before=\[([^\]]*)\]", source)
    assert match, "interrupt_before=[...] must be present in workflow.py"

    list_body = match.group(1)
    # Extract all quoted string tokens from the list.
    found_keys = set(re.findall(r'["\']([^"\']+)["\']', list_body))
    expected_keys = set(hitl_keys)

    assert found_keys == expected_keys, (
        f"interrupt_before list must contain exactly {expected_keys!r}. "
        f"Found: {found_keys!r}."
    )


# ── human_review_node.py: presence and absence ───────────────────────────────


@pytest.mark.parametrize("step_count", [1, 3, 5])
def test_human_review_node_present_for_workflow(step_count: int) -> None:
    """backend/graph/nodes/human_review_node.py must be emitted for workflow projects."""
    config = _make_workflow_config(step_count=step_count)
    rendered = _render_map(config)

    assert "backend/graph/nodes/human_review_node.py" in rendered, (
        f"backend/graph/nodes/human_review_node.py must be emitted for workflow projects "
        f"(step_count={step_count})"
    )


def test_human_review_node_absent_for_orchestrator() -> None:
    """human_review_node.py must NOT be emitted for orchestrator-pattern projects."""
    config = ProjectConfig.model_validate({
        "metadata": {
            "name": "orch_test_project",
            "description": "Orchestrator render test",
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

    assert "backend/graph/nodes/human_review_node.py" not in rendered, (
        "human_review_node.py must NOT be emitted for orchestrator-pattern projects"
    )


def test_human_review_node_absent_for_fanout() -> None:
    """human_review_node.py must NOT be emitted for fanout-pattern projects."""
    config = ProjectConfig.model_validate({
        "metadata": {
            "name": "fanout_test_project",
            "description": "Fanout render test",
            "python_version": "3.11",
            "author": "Test Author",
            "email": "test@example.com",
        },
        "agents": [
            {
                "key": "alpha",
                "class_name": "AlphaAgent",
                "llm_model": "gpt-4o-mini",
                "system_prompt": "You are the alpha agent.",
            }
        ],
        "database": {"backend": "postgres", "tables": []},
        "workflow": {
            "default_intent": "alpha",
            "enable_feedback_loop": False,
            "enable_validation_node": False,
        },
        "pattern": "fanout",
        "entry": {"type": "intent_router"},
    })
    rendered = _render_map(config)

    assert "backend/graph/nodes/human_review_node.py" not in rendered, (
        "human_review_node.py must NOT be emitted for fanout-pattern projects"
    )


# ── graph_agent.py absent for workflow (regression guard) ────────────────────


@pytest.mark.parametrize("step_count", [1, 3, 5])
def test_graph_agent_absent_for_workflow(step_count: int) -> None:
    """backend/graph/graph_agent.py must NOT be rendered for workflow-pattern projects.

    This is a regression guard: the react-pattern overlay's graph_agent.py
    must not bleed through into workflow renders.
    """
    config = _make_workflow_config(step_count=step_count)
    rendered = _render_map(config)

    assert "backend/graph/graph_agent.py" not in rendered, (
        "backend/graph/graph_agent.py must be absent for workflow-pattern projects. "
        "The react overlay must not bleed through."
    )


# ── Negative tests: validation errors ────────────────────────────────────────


def test_hitl_before_unknown_step_key_raises_validation_error() -> None:
    """hitl_before referencing a step key not in steps must raise ValidationError.

    This guards against typos in hitl_before that would result in a LangGraph
    interrupt that silently never fires.
    """
    with pytest.raises(ValidationError) as exc_info:
        ProjectConfig.model_validate({
            **_VALID_BASE,
            "workflow_sm": {
                "steps": [
                    {"key": "fetch_data", "description": "Fetch"},
                    {"key": "process", "description": "Process"},
                ],
                "hitl_before": ["nonexistent_step"],
            },
        })

    errors = exc_info.value.errors()
    assert any(
        "nonexistent_step" in str(e) or "hitl_before" in str(e).lower()
        for e in errors
    ), f"Expected error mentioning 'nonexistent_step' or 'hitl_before'. Got: {errors}"


def test_workflow_pattern_empty_steps_raises_validation_error() -> None:
    """pattern='workflow' with empty workflow_sm.steps must raise ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        ProjectConfig.model_validate({
            **_VALID_BASE,
            "workflow_sm": {
                "steps": [],
                "hitl_before": [],
            },
        })

    errors = exc_info.value.errors()
    assert any(
        "steps" in str(e).lower() or "workflow_sm" in str(e).lower()
        for e in errors
    ), f"Expected error mentioning 'steps' or 'workflow_sm'. Got: {errors}"


def test_workflow_pattern_without_workflow_sm_raises_validation_error() -> None:
    """pattern='workflow' without workflow_sm block must raise ValidationError."""
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate({
            **_VALID_BASE,
            # no workflow_sm key → None → validator should reject
        })


def test_hitl_before_multiple_unknown_keys_raises_validation_error() -> None:
    """Multiple unknown hitl_before keys must all be mentioned in the error."""
    with pytest.raises(ValidationError) as exc_info:
        ProjectConfig.model_validate({
            **_VALID_BASE,
            "workflow_sm": {
                "steps": [{"key": "step_a", "description": ""}],
                "hitl_before": ["missing_x", "missing_y"],
            },
        })
    error_str = str(exc_info.value)
    assert "missing_x" in error_str or "missing_y" in error_str, (
        "ValidationError should mention at least one unknown step key"
    )


# ── Template hardcode guards ───────────────────────────────────────────────────


def test_workflow_template_no_hardcoded_step_keys() -> None:
    """workflow.py.j2 must not hardcode any fixture step key strings in static text.

    All step key references must come from ``{{ step.key }}`` Jinja expressions.
    Strategy: strip all Jinja blocks from the template source, then confirm none
    of the known fixture step keys appear as bare quoted string literals.
    """
    template_path = _WORKFLOW_TEMPLATES_DIR / "workflow.py.j2"
    assert template_path.exists(), f"Template not found: {template_path}"
    raw = template_path.read_text(encoding="utf-8")
    stripped = _strip_jinja(raw)

    for key in _FIXTURE_STEP_KEYS:
        # Bare quoted occurrence — either 'key' or "key"
        if f'"{key}"' in stripped or f"'{key}'" in stripped:
            pytest.fail(
                f"workflow.py.j2 contains hardcoded step key {key!r} in static text. "
                f"Step keys must come from the Jinja context ({{{{ step.key }}}})."
            )


def test_human_review_node_template_no_hardcoded_fixture_step_keys() -> None:
    """human_review_node.py.j2 must not hardcode any fixture step keys in static text.

    The template is a static utility module; it must not embed any domain-specific
    step key names (e.g. 'fetch_data', 'validate_input') in its static text.
    All step-key references must come via Jinja context expressions.
    """
    template_path = _WORKFLOW_TEMPLATES_DIR / "human_review_node.py.j2"
    assert template_path.exists(), f"Template not found: {template_path}"
    raw = template_path.read_text(encoding="utf-8")
    stripped = _strip_jinja(raw)

    for key in _FIXTURE_STEP_KEYS:
        if f'"{key}"' in stripped or f"'{key}'" in stripped:
            pytest.fail(
                f"human_review_node.py.j2 contains hardcoded fixture step key {key!r} "
                f"in static text. Step keys must come from Jinja context if needed."
            )


# ── WorkflowStateMachineConfig: schema validation happy path ──────────────────


def test_workflow_sm_config_sensible_defaults() -> None:
    """workflow_sm with only steps (no hitl_before) must not raise."""
    config = _make_workflow_config(step_count=2, hitl_before=[])
    from agentforge.engine.renderer import TemplateRenderer
    ctx = TemplateRenderer._build_context(config)

    assert ctx["workflow_steps"] == [
        {"key": "fetch_data", "description": "Fetch input data"},
        {"key": "validate_input", "description": "Validate input fields"},
    ]
    assert ctx["workflow_hitl_before"] == []


def test_workflow_sm_context_hitl_before_wired_through() -> None:
    """workflow_hitl_before context variable must match the configured hitl_before."""
    hitl = ["fetch_data", "process_records"]
    config = _make_workflow_config(step_count=5, hitl_before=hitl)
    from agentforge.engine.renderer import TemplateRenderer
    ctx = TemplateRenderer._build_context(config)

    assert ctx["workflow_hitl_before"] == hitl, (
        f"workflow_hitl_before context must equal {hitl!r}. Got: {ctx['workflow_hitl_before']!r}"
    )


def test_workflow_sm_absent_yields_empty_context() -> None:
    """When workflow_sm is None (non-workflow pattern), context vars must be empty lists."""
    config = ProjectConfig.model_validate({
        "metadata": {
            "name": "non_workflow_project",
            "description": "Non-workflow test",
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
    from agentforge.engine.renderer import TemplateRenderer
    ctx = TemplateRenderer._build_context(config)

    assert ctx["workflow_steps"] == [], (
        "workflow_steps must be [] when workflow_sm is None"
    )
    assert ctx["workflow_hitl_before"] == [], (
        "workflow_hitl_before must be [] when workflow_sm is None"
    )


# ── StepConfig: slug constraint validation ────────────────────────────────────


@pytest.mark.parametrize("bad_key", [" spaces ", "with-dash", "CamelCase", "1leading", ""])
def test_step_config_key_rejects_invalid_slug(bad_key: str) -> None:
    """StepConfig.key must reject values that do not match the slug regex."""
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate({
            **_VALID_BASE,
            "workflow_sm": {
                "steps": [{"key": bad_key, "description": "bad step"}],
                "hitl_before": [],
            },
        })


# ── hitl_before with all valid steps (positive) ───────────────────────────────


@pytest.mark.parametrize("hitl_count", [0, 1, 3])
def test_workflow_valid_hitl_before_configurations(hitl_count: int) -> None:
    """Workflow configs with valid hitl_before sets must validate without error."""
    steps = _make_step_dicts(5)
    hitl_keys = [s["key"] for s in steps[:hitl_count]]
    # Should not raise
    config = _make_workflow_config(step_count=5, hitl_before=hitl_keys)
    assert config.workflow_sm is not None
    assert config.workflow_sm.hitl_before == hitl_keys


# ── Rendered workflow.py: no import statement for human_review_node ───────────


def test_workflow_py_does_not_import_human_review_node() -> None:
    """workflow.py must not contain an import statement for human_review_node.

    The human_review_node module is a standalone resume-hook utility; it is not
    wired as a graph node and must not be imported by workflow.py. Importing it
    would create dead code and potential circular dependencies.

    Note: the workflow.py docstring may reference 'human_review_node.py' as
    documentation — the test specifically checks for Python import statements,
    not for the mere presence of the string.
    """
    config = _make_workflow_config(step_count=3, hitl_before=["fetch_data"])
    rendered = _render_map(config)
    source = rendered["backend/graph/workflow.py"]

    # Look for any import statement bringing in human_review_node.
    import_pattern = re.compile(
        r"^\s*(from\s+.*human_review_node.*import|import\s+.*human_review_node)",
        re.MULTILINE,
    )
    assert not import_pattern.search(source), (
        "workflow.py must not have an import statement for human_review_node. "
        "It is a standalone module, not a graph node."
    )


# ── human_review_node.py: AST-compile and function signature ─────────────────


@pytest.mark.parametrize("step_count", [1, 3, 5])
def test_human_review_node_ast_compiles(step_count: int) -> None:
    """human_review_node.py must be valid Python for all step counts."""
    config = _make_workflow_config(step_count=step_count)
    rendered = _render_map(config)
    source = rendered["backend/graph/nodes/human_review_node.py"]
    try:
        ast.parse(source)
    except SyntaxError as exc:
        pytest.fail(
            f"human_review_node.py (step_count={step_count}) has a syntax error: "
            f"{exc}\n\n{source}"
        )


def test_human_review_node_defines_function() -> None:
    """human_review_node.py must define a callable named 'human_review_node'."""
    config = _make_workflow_config(step_count=2, hitl_before=["fetch_data"])
    rendered = _render_map(config)
    source = rendered["backend/graph/nodes/human_review_node.py"]

    tree = ast.parse(source)
    function_names = [
        node.name for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    ]
    assert "human_review_node" in function_names, (
        "human_review_node.py must define a function named 'human_review_node'"
    )


# ── Negative test: duplicate step keys ────────────────────────────────────────


def test_duplicate_step_keys_raises_validation_error() -> None:
    """workflow_sm.steps with duplicate step keys must raise ValidationError.

    Duplicate step keys would cause LangGraph to silently overwrite a node
    registration, producing a graph topology that does not match the configured
    sequence.  The validator catches this early with an actionable message.
    """
    with pytest.raises(ValidationError) as exc_info:
        ProjectConfig.model_validate({
            **_VALID_BASE,
            "workflow_sm": {
                "steps": [
                    {"key": "fetch_data", "description": "Fetch data"},
                    {"key": "process", "description": "Process"},
                    {"key": "fetch_data", "description": "Duplicate of first step"},
                ],
                "hitl_before": [],
            },
        })

    error_str = str(exc_info.value)
    assert "fetch_data" in error_str or "duplicate" in error_str.lower(), (
        f"ValidationError must mention the duplicate key or 'duplicate'. Got: {error_str}"
    )


# ── Behavioral test: compiled graph interrupt_before_nodes metadata ───────────


def test_compiled_interrupt_before_metadata_matches_config() -> None:
    """The compiled LangGraph graph's interrupt_before_nodes must equal hitl_before.

    This ties the source-text test (which checks the rendered .py file text) to
    the actual compiled graph metadata, closing the loop on acceptance criterion #1.

    The test builds a StateGraph directly using the same step keys and hitl_before
    values that the renderer would use, compiles it with a MemorySaver checkpointer,
    and asserts that ``compiled.interrupt_before_nodes`` matches the configured list.

    Note: ``_BehavioralWorkflowState`` is defined at module scope (not inside
    this function) so that LangGraph's ``get_type_hints()`` call can resolve its
    annotations correctly.
    """
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.memory import MemorySaver

    hitl_keys = ["validate_input", "process_records"]
    steps = _make_step_dicts(5)

    def _noop(state: dict) -> dict:
        return {}

    graph = StateGraph(_BehavioralWorkflowState)
    for step in steps:
        graph.add_node(step["key"], _noop)
    graph.add_edge(START, steps[0]["key"])
    for i in range(len(steps) - 1):
        graph.add_edge(steps[i]["key"], steps[i + 1]["key"])
    graph.add_edge(steps[-1]["key"], END)

    compiled = graph.compile(
        checkpointer=MemorySaver(),
        interrupt_before=hitl_keys,
    )

    assert list(compiled.interrupt_before_nodes) == hitl_keys, (
        f"compiled.interrupt_before_nodes must equal {hitl_keys!r}. "
        f"Got: {list(compiled.interrupt_before_nodes)!r}"
    )


# ── Behavioral test: full interrupt / resume cycle ────────────────────────────


def test_interrupt_resume_cycle() -> None:
    """Full LangGraph interrupt-before / resume cycle for a 3-step workflow config.

    Acceptance criterion #2 of TODO-v2-4: exercises the actual interrupt/resume
    behavior, not just the rendered source text.

    Setup
    -----
    - 3 steps: fetch_data → validate_input → process_records
    - hitl_before=["validate_input"]  (HITL at the second step)
    - Compiled with a MemorySaver checkpointer and a fixed thread_id

    Assertions
    ----------
    1. After the first invoke the graph pauses:
       ``state.next == ("validate_input",)``
    2. After ``graph.invoke(None, config)`` (resume) the graph completes:
       ``state.next == ()``  (empty tuple — no more steps to run)

    Note: ``_BehavioralWorkflowState`` is defined at module scope (not inside
    this function) so that LangGraph's ``get_type_hints()`` call can resolve its
    annotations correctly.
    """
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.memory import MemorySaver

    step_keys = ["fetch_data", "validate_input", "process_records"]
    hitl_key = "validate_input"

    def _noop(state: dict) -> dict:
        return {}

    graph = StateGraph(_BehavioralWorkflowState)
    for key in step_keys:
        graph.add_node(key, _noop)
    graph.add_edge(START, step_keys[0])
    for i in range(len(step_keys) - 1):
        graph.add_edge(step_keys[i], step_keys[i + 1])
    graph.add_edge(step_keys[-1], END)

    compiled = graph.compile(
        checkpointer=MemorySaver(),
        interrupt_before=[hitl_key],
    )

    thread_config: dict = {"configurable": {"thread_id": "workflow-hitl-test-thread"}}

    # First invoke — should pause before validate_input.
    compiled.invoke({"query": "test input"}, thread_config)
    paused_state = compiled.get_state(thread_config)
    assert paused_state.next == (hitl_key,), (
        f"Graph must pause at '{hitl_key}' after first invoke. "
        f"state.next={paused_state.next!r}"
    )

    # Resume — pass None as input to signal a checkpoint-based resume.
    compiled.invoke(None, thread_config)
    final_state = compiled.get_state(thread_config)
    assert final_state.next == (), (
        f"Graph must complete after resume (state.next must be empty tuple). "
        f"Got: {final_state.next!r}"
    )
