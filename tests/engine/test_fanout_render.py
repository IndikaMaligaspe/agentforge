"""
Tests for the fanout pattern template overlay (TODO-v2-3).

Covers:
- Rendering a ``pattern: fanout`` fixture with varying agent counts (1, 3, 5)
  produces files that all AST-compile without syntax errors.
- The rendered workflow.py declares a conditional-send edge from the
  ``"orchestrator"`` node (``add_conditional_edges`` call present), matching
  the static N-way fan-out shape.
- The rendered workflow.py declares one node per configured agent key
  (``add_node`` call per agent).
- The fanout state type uses ``Annotated[list, operator.add]`` — confirmed by
  checking both ``Annotated`` and ``operator.add`` appear in the rendered source.
- Parametrized over ``reducer ∈ {"concat", "merge_dict"}``: the rendered
  reducer_node.py contains ONLY the active strategy helper; the other is absent.
- No bare literal integers adjacent to agent count appear in the template
  source files (hardcode guard — scans stripped Jinja source).
- No hardcoded agent key strings appear in the template source files.
- No hardcoded state-field names (e.g. ``"fanout_results"``) appear in the
  static (non-Jinja) text of the template files.
- ``pattern: fanout`` does NOT emit ``backend/graph/graph_agent.py``
  (regression guard against react overlay bleeding through).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

from agentforge.engine.renderer import TemplateRenderer
from agentforge.schema.models import (
    AgentConfig,
    DatabaseConfig,
    FanoutConfig,
    LLMModel,
    ProjectConfig,
    ProjectMetadata,
    WorkflowConfig,
)


# ── Template paths (for hardcode-guard tests) ─────────────────────────────────

_FANOUT_TEMPLATES_DIR = (
    Path(__file__).parent.parent.parent
    / "agentforge"
    / "templates"
    / "patterns"
    / "fanout"
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_agent_entries(count: int) -> list[dict]:
    """Build ``count`` minimal agent dicts with distinct keys and class names."""
    suffixes = ["alpha", "beta", "gamma", "delta", "epsilon"]
    class_names = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon"]
    return [
        {
            "key": suffixes[i],
            "class_name": f"{class_names[i]}Agent",
            "llm_model": "gpt-4o-mini",
            "system_prompt": f"You are the {suffixes[i]} agent.",
        }
        for i in range(count)
    ]


def _make_fanout_config(
    agent_count: int = 3,
    reducer: Literal["concat", "merge_dict"] = "concat",
    results_field: str = "fanout_results",
) -> ProjectConfig:
    """Build a minimal valid ProjectConfig with ``pattern: fanout``.

    Notes
    -----
    - ``workflow.enable_feedback_loop`` and ``enable_validation_node`` are set
      to ``False`` because these flags are incompatible with the fanout pattern
      (enforced by ``check_workflow_flags_pattern_compat`` validator).
    - ``workflow.default_intent`` must match one of the agent keys; we use the
      first agent key.
    """
    agents = _make_agent_entries(agent_count)
    first_key = agents[0]["key"]
    return ProjectConfig.model_validate({
        "metadata": {
            "name": "fanout_test_project",
            "description": "Fanout render test",
            "python_version": "3.11",
            "author": "Test Author",
            "email": "test@example.com",
        },
        "agents": agents,
        "database": {"backend": "postgres", "tables": []},
        "workflow": {
            "default_intent": first_key,
            "enable_feedback_loop": False,
            "enable_validation_node": False,
        },
        "pattern": "fanout",
        "entry": {"type": "intent_router"},
        "fanout": {
            "reducer": reducer,
            "results_field": results_field,
        },
    })


def _render_map(config: ProjectConfig) -> dict[str, str]:
    """Render all templates and return {relative_path: content}."""
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
}


# ── AST-compile: all generated .py files ─────────────────────────────────────


@pytest.mark.parametrize("agent_count", [1, 3, 5])
@pytest.mark.parametrize("reducer", ["concat", "merge_dict"])
def test_fanout_all_py_files_ast_compile(agent_count: int, reducer: str) -> None:
    """All rendered .py files for a fanout project must parse as valid Python."""
    config = _make_fanout_config(agent_count=agent_count, reducer=reducer)
    rendered = _render_map(config)

    py_files = {path: content for path, content in rendered.items() if path.endswith(".py")}
    assert py_files, "No .py files were rendered for fanout project"

    for path, source in py_files.items():
        try:
            ast.parse(source)
        except SyntaxError as exc:
            pytest.fail(
                f"Fanout render (agents={agent_count}, reducer={reducer!r}) "
                f"produced invalid Python in {path!r}:\n{exc}\n\n{source}"
            )


# ── workflow.py: conditional-send edge from orchestrator ──────────────────────


@pytest.mark.parametrize("agent_count", [1, 3, 5])
def test_fanout_workflow_has_conditional_edge_from_orchestrator(agent_count: int) -> None:
    """workflow.py must wire a conditional edge from the 'orchestrator' node.

    The conditional edge is what triggers the Send fan-out.  Both
    ``add_conditional_edges`` and ``"orchestrator"`` must appear together
    in the rendered workflow.py.
    """
    config = _make_fanout_config(agent_count=agent_count)
    rendered = _render_map(config)

    path = "backend/graph/workflow.py"
    assert path in rendered, f"{path!r} missing from fanout render output"
    source = rendered[path]

    assert "add_conditional_edges" in source, (
        "fanout workflow.py must call add_conditional_edges (for orchestrator fan-out)"
    )
    assert '"orchestrator"' in source or "'orchestrator'" in source, (
        "fanout workflow.py must reference the 'orchestrator' node name"
    )


@pytest.mark.parametrize("agent_count", [1, 3, 5])
def test_fanout_workflow_has_node_per_agent(agent_count: int) -> None:
    """workflow.py must register one add_node call per configured agent key."""
    agents = _make_agent_entries(agent_count)
    config = _make_fanout_config(agent_count=agent_count)
    rendered = _render_map(config)
    source = rendered["backend/graph/workflow.py"]

    for agent in agents:
        key = agent["key"]
        assert f'"{key}"' in source or f"'{key}'" in source, (
            f"fanout workflow.py must contain the agent key {key!r} "
            f"(agent_count={agent_count})"
        )
        # Confirm there's an add_node call for this agent.
        assert f'add_node("{key}"' in source or f"add_node('{key}'" in source, (
            f"fanout workflow.py must call add_node({key!r}, ...) "
            f"(agent_count={agent_count})"
        )


# ── workflow.py: Annotated[list, operator.add] reducer ───────────────────────


@pytest.mark.parametrize("agent_count", [1, 3, 5])
def test_fanout_workflow_uses_annotated_list_reducer(agent_count: int) -> None:
    """workflow.py must declare Annotated[list, operator.add] on the results field.

    The test checks the rendered *output* (not the template bytes) so it
    validates the rendered shape, not specific Jinja syntax.
    """
    config = _make_fanout_config(agent_count=agent_count)
    rendered = _render_map(config)
    source = rendered["backend/graph/workflow.py"]

    assert "Annotated" in source, (
        "fanout workflow.py must import/use Annotated for the reducer state field"
    )
    assert "operator.add" in source, (
        "fanout workflow.py must use operator.add as the reducer function"
    )


# ── orchestrator_node.py: Send imports and fan-out ────────────────────────────


@pytest.mark.parametrize("agent_count", [1, 3, 5])
def test_fanout_orchestrator_node_uses_send(agent_count: int) -> None:
    """orchestrator_node.py must import Send and return a list of Send objects."""
    config = _make_fanout_config(agent_count=agent_count)
    rendered = _render_map(config)

    path = "backend/graph/nodes/orchestrator_node.py"
    assert path in rendered, f"{path!r} missing from fanout render output"
    source = rendered[path]

    assert "Send" in source, (
        "orchestrator_node.py must use the LangGraph Send type"
    )
    # All agent keys should appear in the list
    agents = _make_agent_entries(agent_count)
    for agent in agents:
        key = agent["key"]
        assert f'"{key}"' in source or f"'{key}'" in source, (
            f"orchestrator_node.py must contain agent key {key!r} "
            f"(agent_count={agent_count})"
        )


@pytest.mark.parametrize("agent_count", [1, 3, 5])
def test_fanout_orchestrator_node_ast_compiles(agent_count: int) -> None:
    """orchestrator_node.py must be valid Python for all agent counts."""
    config = _make_fanout_config(agent_count=agent_count)
    rendered = _render_map(config)
    source = rendered["backend/graph/nodes/orchestrator_node.py"]
    try:
        ast.parse(source)
    except SyntaxError as exc:
        pytest.fail(
            f"orchestrator_node.py (agent_count={agent_count}) has a syntax error: "
            f"{exc}\n\n{source}"
        )


# ── reducer_node.py: only the active strategy helper is emitted ──────────────


@pytest.mark.parametrize("reducer", ["concat", "merge_dict"])
def test_fanout_reducer_node_emits_only_active_strategy_helper(reducer: str) -> None:
    """reducer_node.py must emit ONLY the active strategy helper; the other must be absent.

    The template gates the two helper bodies with ``{% if fanout_reducer == "concat" %}``
    so the generated file is free of dead code.

    - When reducer='concat':  ``list(results)`` present, ``merged.update`` absent.
    - When reducer='merge_dict':  ``merged.update`` present, ``list(results)`` absent.

    We use merged.update (not bare merged) as the discriminator because
    the module docstring mentions "merged" in prose regardless of active strategy.
    """
    config = _make_fanout_config(reducer=reducer)
    rendered = _render_map(config)

    path = "backend/graph/nodes/reducer_node.py"
    assert path in rendered, f"{path!r} missing from fanout render output"
    source = rendered[path]

    if reducer == "concat":
        assert "list(results)" in source, (
            "reducer_node.py with reducer='concat' must contain 'list(results)'"
        )
        assert "merged.update" not in source, (
            "reducer_node.py with reducer='concat' must NOT contain 'merged.update' "
            "(dead code from the merge_dict helper)"
        )
    else:
        assert "merged.update" in source, (
            "reducer_node.py with reducer='merge_dict' must contain 'merged.update'"
        )
        assert "list(results)" not in source, (
            "reducer_node.py with reducer='merge_dict' must NOT contain 'list(results)' "
            "(dead code from the concat helper)"
        )


@pytest.mark.parametrize("reducer", ["concat", "merge_dict"])
def test_fanout_reducer_node_active_strategy_string_present(reducer: str) -> None:
    """The configured reducer strategy string must appear in reducer_node.py.

    The scaffold-time value is embedded as ``_REDUCER_STRATEGY = "..."``
    (injected from ``fanout_reducer`` context).  Checking its presence
    verifies the template rendered the config value rather than a hardcoded
    literal.
    """
    config = _make_fanout_config(reducer=reducer)
    rendered = _render_map(config)
    source = rendered["backend/graph/nodes/reducer_node.py"]

    assert f'"{reducer}"' in source or f"'{reducer}'" in source, (
        f"reducer_node.py must contain the configured reducer strategy {reducer!r}. "
        "The template must render the config value, not a hardcoded literal."
    )


@pytest.mark.parametrize("reducer", ["concat", "merge_dict"])
def test_fanout_reducer_node_ast_compiles(reducer: str) -> None:
    """reducer_node.py must be valid Python for both reducer strategies."""
    config = _make_fanout_config(reducer=reducer)
    rendered = _render_map(config)
    source = rendered["backend/graph/nodes/reducer_node.py"]
    try:
        ast.parse(source)
    except SyntaxError as exc:
        pytest.fail(
            f"reducer_node.py (reducer={reducer!r}) has a syntax error: "
            f"{exc}\n\n{source}"
        )


# ── results_field: custom state field name wired through ──────────────────────


def test_fanout_custom_results_field_appears_in_workflow() -> None:
    """A non-default results_field value must appear in the rendered workflow.py."""
    config = _make_fanout_config(results_field="campaign_scores")
    rendered = _render_map(config)
    source = rendered["backend/graph/workflow.py"]

    assert "campaign_scores" in source, (
        "fanout workflow.py must use the custom results_field value 'campaign_scores'. "
        "The template must render the config value, not the default 'fanout_results'."
    )


def test_fanout_custom_results_field_appears_in_orchestrator_node() -> None:
    """A non-default results_field value must appear in orchestrator_node.py."""
    config = _make_fanout_config(results_field="campaign_scores")
    rendered = _render_map(config)
    source = rendered["backend/graph/nodes/orchestrator_node.py"]

    assert "campaign_scores" in source, (
        "orchestrator_node.py must use the custom results_field value 'campaign_scores'."
    )


def test_fanout_custom_results_field_appears_in_reducer_node() -> None:
    """A non-default results_field value must appear in reducer_node.py."""
    config = _make_fanout_config(results_field="campaign_scores")
    rendered = _render_map(config)
    source = rendered["backend/graph/nodes/reducer_node.py"]

    assert "campaign_scores" in source, (
        "reducer_node.py must use the custom results_field value 'campaign_scores'."
    )


# ── results_field: slug regex rejects invalid values ─────────────────────────


@pytest.mark.parametrize("bad", [" spaces ", "with-dash", "CamelCase", "1leading", ""])
def test_fanout_results_field_rejects_invalid_slug(bad: str) -> None:
    """FanoutConfig.results_field must reject values that do not match the slug regex.

    Valid slugs: lowercase, start with a letter, contain only [a-z0-9_].
    Invalid: leading digit, uppercase, hyphens, spaces, empty string.
    """
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate({
            **_VALID_BASE,
            "fanout": {"results_field": bad},
        })


# ── Template hardcode guards (scan template source files) ─────────────────────


def test_orchestrator_node_template_no_hardcoded_agent_count() -> None:
    """orchestrator_node.py.j2 must not contain bare integer literals adjacent to agent-count context.

    Scans the static (non-Jinja) text of the template file to confirm no
    numeric literal appears where the agent count should come from the config.
    """
    template_path = _FANOUT_TEMPLATES_DIR / "orchestrator_node.py.j2"
    assert template_path.exists(), f"Template not found: {template_path}"
    raw = template_path.read_text(encoding="utf-8")
    stripped = _strip_jinja(raw)

    # No bare integer should appear adjacent to common count-related words.
    assert not re.search(r"\bagent_count\s*[=:]\s*\d+", stripped), (
        "orchestrator_node.py.j2 must not hardcode an agent count integer. "
        "Use {{ agent_keys | length }} or equivalent Jinja expression."
    )


def test_workflow_template_no_hardcoded_state_field_name() -> None:
    """workflow.py.j2 (fanout) must not hardcode 'fanout_results' in static text.

    All state field name references must come from the ``{{ fanout_results_field }}``
    Jinja expression so the field name can be customised via FanoutConfig.
    """
    template_path = _FANOUT_TEMPLATES_DIR / "workflow.py.j2"
    assert template_path.exists(), f"Template not found: {template_path}"
    raw = template_path.read_text(encoding="utf-8")
    stripped = _strip_jinja(raw)

    # The default field name "fanout_results" must NOT appear as a bare string
    # literal in the static (non-Jinja) portion of the template.
    assert "fanout_results" not in stripped, (
        "workflow.py.j2 (fanout) must not hardcode 'fanout_results' in static text. "
        "Use {{ fanout_results_field }} so the field name comes from FanoutConfig."
    )


def test_reducer_node_template_no_hardcoded_state_field_name() -> None:
    """reducer_node.py.j2 must not hardcode 'fanout_results' in static text."""
    template_path = _FANOUT_TEMPLATES_DIR / "reducer_node.py.j2"
    assert template_path.exists(), f"Template not found: {template_path}"
    raw = template_path.read_text(encoding="utf-8")
    stripped = _strip_jinja(raw)

    assert "fanout_results" not in stripped, (
        "reducer_node.py.j2 must not hardcode 'fanout_results' in static text. "
        "Use {{ fanout_results_field }} so the field name comes from FanoutConfig."
    )


def test_orchestrator_node_template_no_hardcoded_agent_keys() -> None:
    """The rendered _AGENT_KEYS list must contain exactly the configured agent keys.

    Uses a regex to extract the string tokens from the rendered _AGENT_KEYS list
    and performs set-equality against the expected agent keys.  This confirms that:

    1. The list is sourced from context (Jinja loop), not hardcoded.
    2. No extra bare-string quoted agent-key-like tokens appear elsewhere
       in the module body outside the list literal.
    """
    agent_count = 3
    agents = _make_agent_entries(agent_count)
    expected_keys = {a["key"] for a in agents}

    config = _make_fanout_config(agent_count=agent_count)
    rendered = _render_map(config)

    path = "backend/graph/nodes/orchestrator_node.py"
    assert path in rendered, f"{path!r} missing from fanout render output"
    source = rendered[path]

    # Extract the _AGENT_KEYS list literal block from the rendered source.
    # Pattern: _AGENT_KEYS: list[str] = [ ... ]
    list_match = re.search(
        r"_AGENT_KEYS\s*:\s*list\[str\]\s*=\s*\[([^\]]*)\]",
        source,
        re.DOTALL,
    )
    assert list_match, (
        "orchestrator_node.py must define _AGENT_KEYS as a list[str] literal"
    )

    list_body = list_match.group(1)
    # Extract all quoted string tokens from the list body.
    rendered_keys = set(re.findall(r'["\']([^"\']+)["\']', list_body))

    assert rendered_keys == expected_keys, (
        f"_AGENT_KEYS in orchestrator_node.py must equal the configured agent keys. "
        f"Expected {expected_keys!r}, got {rendered_keys!r}."
    )

    # Confirm no other bare quoted agent-key-like tokens appear outside the list.
    # Strip the list block from the source and scan for quoted versions of each key.
    source_without_list = source[: list_match.start()] + source[list_match.end():]
    for key in expected_keys:
        # Allow the key in comments/docstrings (single-quoted or unquoted in text)
        # but flag bare string literals like "alpha" or 'alpha' in code.
        extra = re.findall(rf'(?<![#\w])["\']({re.escape(key)})["\']', source_without_list)
        assert not extra, (
            f"Agent key {key!r} appears as a bare quoted string outside _AGENT_KEYS "
            f"in orchestrator_node.py. Agent keys must only be sourced from _AGENT_KEYS."
        )


# ── graph_agent.py absent for fanout (regression guard) ──────────────────────


@pytest.mark.parametrize("agent_count", [1, 3, 5])
def test_graph_agent_absent_for_fanout(agent_count: int) -> None:
    """backend/graph/graph_agent.py must NOT be rendered for fanout-pattern projects.

    This is a regression guard: the react-pattern overlay's graph_agent.py
    must not bleed through into fanout renders.
    """
    config = _make_fanout_config(agent_count=agent_count)
    rendered = _render_map(config)

    assert "backend/graph/graph_agent.py" not in rendered, (
        "backend/graph/graph_agent.py must be absent for fanout-pattern projects. "
        "The react overlay must not bleed through."
    )


# ── fanout-specific files present ────────────────────────────────────────────


@pytest.mark.parametrize("agent_count", [1, 3, 5])
def test_fanout_specific_files_are_present(agent_count: int) -> None:
    """orchestrator_node.py and reducer_node.py must be emitted for fanout projects."""
    config = _make_fanout_config(agent_count=agent_count)
    rendered = _render_map(config)

    assert "backend/graph/nodes/orchestrator_node.py" in rendered, (
        "backend/graph/nodes/orchestrator_node.py must be emitted for fanout projects"
    )
    assert "backend/graph/nodes/reducer_node.py" in rendered, (
        "backend/graph/nodes/reducer_node.py must be emitted for fanout projects"
    )


# ── fanout-specific files absent for non-fanout patterns ─────────────────────


def test_fanout_specific_files_absent_for_orchestrator() -> None:
    """orchestrator_node.py and reducer_node.py must NOT be emitted for orchestrator projects."""
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

    assert "backend/graph/nodes/orchestrator_node.py" not in rendered, (
        "backend/graph/nodes/orchestrator_node.py must NOT be emitted for orchestrator projects"
    )
    assert "backend/graph/nodes/reducer_node.py" not in rendered, (
        "backend/graph/nodes/reducer_node.py must NOT be emitted for orchestrator projects"
    )


# ── FanoutConfig schema: round-trip with defaults ────────────────────────────


def test_fanout_config_sensible_defaults_no_error() -> None:
    """A fanout config without an explicit ``fanout`` sub-block must not raise.

    The renderer must pull sensible defaults (reducer='concat',
    results_field='fanout_results') from the schema defaults.
    """
    config = ProjectConfig.model_validate({
        "metadata": {
            "name": "fanout_defaults_project",
            "description": "Fanout defaults test",
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
        # No "fanout" sub-block — defaults must apply.
    })
    # Build context to confirm no KeyError or AttributeError.
    from agentforge.engine.renderer import TemplateRenderer
    ctx = TemplateRenderer._build_context(config)
    assert ctx["fanout_reducer"] == "concat", (
        "Default fanout_reducer must be 'concat' when no fanout sub-block is provided"
    )
    assert ctx["fanout_results_field"] == "fanout_results", (
        "Default fanout_results_field must be 'fanout_results' when no fanout sub-block is provided"
    )
