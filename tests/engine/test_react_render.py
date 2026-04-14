"""
Tests for the react pattern template overlay (TODO-v2-2).

Covers:
- Rendering a ``pattern: react`` config produces agent files that AST-compile.
- The rendered agent.py contains the two-node graph structure (agent + tools nodes).
- The conditional edge wiring (should_continue / END) is present.
- The max_steps cap is wired through from the ReactConfig value, not as a hardcoded
  literal inside the template source.
- The temperature value is wired through from the ReactConfig value, not as a
  hardcoded literal inside the template source.
- Parametrized over max_steps in {3, 12} and tool_choice in {"auto", "required"} to
  confirm that all four combinations produce distinct, valid, compilable output.
- ``backend/graph/graph_agent.py`` is emitted for react projects and is absent for
  orchestrator projects (regression guard).
- No Madgicx-specific strings appear in any rendered file.
- The shared ``agent.py.j2`` template is NOT modified — orchestrator projects still
  render the single-invoke stub.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Literal

import pytest

from agentforge.engine.renderer import TemplateRenderer
from agentforge.schema.models import (
    AgentConfig,
    DatabaseConfig,
    LLMModel,
    ProjectConfig,
    ProjectMetadata,
    ReactConfig,
    WorkflowConfig,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_react_config(
    max_steps: int = 12,
    tool_choice: Literal["auto", "required"] = "auto",
    temperature: float = 0.0,
) -> ProjectConfig:
    """Build a minimal valid ProjectConfig with pattern='react' and the given ReactConfig."""
    return ProjectConfig.model_validate({
        "metadata": {
            "name": "react_test_project",
            "description": "ReAct render test",
            "python_version": "3.11",
            "author": "Test Author",
            "email": "test@example.com",
        },
        "agents": [
            {
                "key": "search",
                "class_name": "SearchAgent",
                "llm_model": "gpt-4o-mini",
                "system_prompt": "You are a helpful search assistant.",
                "tools": [
                    {
                        "name": "web_search",
                        "description": "Search the web for information",
                    }
                ],
                "needs_validation": False,
            }
        ],
        "database": {"backend": "postgres", "tables": []},
        "workflow": {
            "default_intent": "search",
            "enable_feedback_loop": True,
            "enable_validation_node": True,
        },
        "pattern": "react",
        "entry": {"type": "intent_router"},
        "react": {
            "max_steps": max_steps,
            "tool_choice": tool_choice,
            "temperature": temperature,
        },
    })


def _make_orchestrator_config() -> ProjectConfig:
    """Build a minimal legacy (orchestrator) config for regression checks."""
    return ProjectConfig.model_validate({
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


def _render_map(config: ProjectConfig) -> dict[str, str]:
    """Render all templates and return {relative_path: content}."""
    renderer = TemplateRenderer()
    return {str(path): content for path, content in renderer.render_all(config)}


# ── AST-compile: agent files ──────────────────────────────────────────────────


@pytest.mark.parametrize("max_steps", [3, 12])
@pytest.mark.parametrize("tool_choice", ["auto", "required"])
def test_react_agent_compiles(max_steps: int, tool_choice: str) -> None:
    """Rendered react agent.py must parse as valid Python for all config combos."""
    config = _make_react_config(max_steps=max_steps, tool_choice=tool_choice)
    rendered = _render_map(config)
    agent_path = "backend/agents/search_agent.py"
    assert agent_path in rendered, f"{agent_path} missing from react render output"
    source = rendered[agent_path]
    try:
        ast.parse(source)
    except SyntaxError as exc:
        pytest.fail(
            f"react agent.py (max_steps={max_steps}, tool_choice={tool_choice!r}) "
            f"has a syntax error: {exc}\n\n{source}"
        )


# ── AST-compile: graph_agent.py ───────────────────────────────────────────────


@pytest.mark.parametrize("max_steps", [3, 12])
@pytest.mark.parametrize("tool_choice", ["auto", "required"])
def test_react_graph_agent_compiles(max_steps: int, tool_choice: str) -> None:
    """Rendered backend/graph/graph_agent.py must parse as valid Python."""
    config = _make_react_config(max_steps=max_steps, tool_choice=tool_choice)
    rendered = _render_map(config)
    path = "backend/graph/graph_agent.py"
    assert path in rendered, f"{path} missing from react render output"
    source = rendered[path]
    try:
        ast.parse(source)
    except SyntaxError as exc:
        pytest.fail(
            f"graph_agent.py (max_steps={max_steps}, tool_choice={tool_choice!r}) "
            f"has a syntax error: {exc}\n\n{source}"
        )


# ── Two-node graph structure ──────────────────────────────────────────────────


@pytest.mark.parametrize("max_steps", [3, 12])
@pytest.mark.parametrize("tool_choice", ["auto", "required"])
def test_react_agent_has_two_node_graph(max_steps: int, tool_choice: str) -> None:
    """Rendered react agent.py must declare both 'agent' and 'tools' graph nodes."""
    config = _make_react_config(max_steps=max_steps, tool_choice=tool_choice)
    rendered = _render_map(config)
    source = rendered["backend/agents/search_agent.py"]

    # Both add_node calls must be present with the correct names.
    assert 'add_node("agent"' in source or "add_node('agent'" in source, (
        "react agent.py must add an 'agent' node to the StateGraph"
    )
    assert 'add_node("tools"' in source or "add_node('tools'" in source, (
        "react agent.py must add a 'tools' node to the StateGraph"
    )


@pytest.mark.parametrize("max_steps", [3, 12])
@pytest.mark.parametrize("tool_choice", ["auto", "required"])
def test_react_graph_agent_has_two_node_graph(max_steps: int, tool_choice: str) -> None:
    """Rendered graph_agent.py must declare both 'agent' and 'tools' graph nodes."""
    config = _make_react_config(max_steps=max_steps, tool_choice=tool_choice)
    rendered = _render_map(config)
    source = rendered["backend/graph/graph_agent.py"]

    assert 'add_node("agent"' in source or "add_node('agent'" in source, (
        "graph_agent.py must add an 'agent' node to the StateGraph"
    )
    assert 'add_node("tools"' in source or "add_node('tools'" in source, (
        "graph_agent.py must add a 'tools' node to the StateGraph"
    )


# ── Conditional edge wiring ───────────────────────────────────────────────────


@pytest.mark.parametrize("max_steps", [3, 12])
@pytest.mark.parametrize("tool_choice", ["auto", "required"])
def test_react_agent_has_conditional_edge(max_steps: int, tool_choice: str) -> None:
    """Rendered react agent.py must wire a conditional edge from the agent node."""
    config = _make_react_config(max_steps=max_steps, tool_choice=tool_choice)
    rendered = _render_map(config)
    source = rendered["backend/agents/search_agent.py"]

    assert "add_conditional_edges" in source, (
        "react agent.py must use add_conditional_edges for the agent->tools conditional"
    )
    # The tools-back-to-agent edge must also be wired.
    assert 'add_edge("tools"' in source or "add_edge('tools'" in source, (
        "react agent.py must wire 'tools' -> 'agent' back-edge"
    )


@pytest.mark.parametrize("max_steps", [3, 12])
@pytest.mark.parametrize("tool_choice", ["auto", "required"])
def test_react_graph_agent_has_conditional_edge(max_steps: int, tool_choice: str) -> None:
    """Rendered graph_agent.py must wire a conditional edge from the agent node."""
    config = _make_react_config(max_steps=max_steps, tool_choice=tool_choice)
    rendered = _render_map(config)
    source = rendered["backend/graph/graph_agent.py"]

    assert "add_conditional_edges" in source, (
        "graph_agent.py must use add_conditional_edges for the agent->tools conditional"
    )
    assert 'add_edge("tools"' in source or "add_edge('tools'" in source, (
        "graph_agent.py must wire 'tools' -> 'agent' back-edge"
    )


# ── max_steps wiring: value from config, not template literal ────────────────


@pytest.mark.parametrize("max_steps", [3, 12])
@pytest.mark.parametrize("tool_choice", ["auto", "required"])
def test_react_agent_max_steps_value_present(max_steps: int, tool_choice: str) -> None:
    """The max_steps value must appear in the rendered agent.py output."""
    config = _make_react_config(max_steps=max_steps, tool_choice=tool_choice)
    rendered = _render_map(config)
    source = rendered["backend/agents/search_agent.py"]

    assert str(max_steps) in source, (
        f"Expected max_steps value {max_steps!r} to appear in rendered agent.py. "
        "The template must render the config value, not a hardcoded literal."
    )


@pytest.mark.parametrize("max_steps", [3, 12])
@pytest.mark.parametrize("tool_choice", ["auto", "required"])
def test_react_agent_tool_choice_value_present(max_steps: int, tool_choice: str) -> None:
    """The tool_choice value must appear in the rendered agent.py output."""
    config = _make_react_config(max_steps=max_steps, tool_choice=tool_choice)
    rendered = _render_map(config)
    source = rendered["backend/agents/search_agent.py"]

    assert tool_choice in source, (
        f"Expected tool_choice value {tool_choice!r} to appear in rendered agent.py. "
        "The template must render the config value, not a hardcoded literal."
    )


# ── temperature wiring: value from config, not template literal ───────────────


@pytest.mark.parametrize("temperature", [0.0, 0.7])
def test_react_agent_temperature_value_present(temperature: float) -> None:
    """The configured temperature value must appear in the rendered agent.py output."""
    config = _make_react_config(temperature=temperature)
    rendered = _render_map(config)
    source = rendered["backend/agents/search_agent.py"]

    assert str(temperature) in source, (
        f"Expected temperature value {temperature!r} to appear in rendered agent.py. "
        "The template must render the config value, not a hardcoded literal."
    )


@pytest.mark.parametrize("temperature", [0.0, 0.7])
def test_react_graph_agent_temperature_value_present(temperature: float) -> None:
    """The configured temperature value must appear in the rendered graph_agent.py output."""
    config = _make_react_config(temperature=temperature)
    rendered = _render_map(config)
    source = rendered["backend/graph/graph_agent.py"]

    assert str(temperature) in source, (
        f"Expected temperature value {temperature!r} to appear in rendered graph_agent.py. "
        "The template must render the config value, not a hardcoded literal."
    )


def test_react_agent_template_contains_no_hardcoded_max_steps() -> None:
    """The template file itself must not contain bare integer literals adjacent to max_steps.

    The template must use the Jinja expression ``{{ react_max_steps }}`` rather
    than baking a numeric constant into the source.  This test reads the raw
    .j2 file, strips all Jinja2 blocks, and confirms no bare integer literal
    appears adjacent to 'max_steps' in the static text.
    """
    template_path = (
        Path(__file__).parent.parent.parent
        / "agentforge"
        / "templates"
        / "patterns"
        / "react"
        / "agent.py.j2"
    )
    assert template_path.exists(), f"Template not found: {template_path}"
    raw = template_path.read_text(encoding="utf-8")

    # Strip all Jinja2 expression/statement blocks from the source, then check
    # that no bare hardcoded integer appears adjacent to max_steps in static text.
    jinja_stripped = re.sub(r"\{[{%#].*?[}%#]\}", "", raw, flags=re.DOTALL)

    assert not re.search(r"max_steps\s*[=:]\s*\d+", jinja_stripped), (
        "Found a bare integer literal adjacent to 'max_steps' in the static "
        "(non-Jinja) text of agent.py.j2. Use {{ react_max_steps }} instead."
    )


def test_react_agent_template_contains_no_hardcoded_temperature() -> None:
    """The template file itself must not contain bare integer literals adjacent to temperature.

    The template must use the Jinja expression ``{{ react_temperature }}`` rather
    than baking a numeric constant (e.g. ``temperature=0``) into the source.
    """
    template_path = (
        Path(__file__).parent.parent.parent
        / "agentforge"
        / "templates"
        / "patterns"
        / "react"
        / "agent.py.j2"
    )
    assert template_path.exists(), f"Template not found: {template_path}"
    raw = template_path.read_text(encoding="utf-8")

    jinja_stripped = re.sub(r"\{[{%#].*?[}%#]\}", "", raw, flags=re.DOTALL)

    assert not re.search(r"temperature\s*=\s*\d", jinja_stripped), (
        "Found a bare integer literal adjacent to 'temperature' in the static "
        "(non-Jinja) text of agent.py.j2. Use {{ react_temperature }} instead."
    )


def test_react_graph_agent_template_contains_no_hardcoded_max_steps() -> None:
    """The graph_agent.py.j2 template must not contain bare integers adjacent to max_steps."""
    template_path = (
        Path(__file__).parent.parent.parent
        / "agentforge"
        / "templates"
        / "patterns"
        / "react"
        / "graph_agent.py.j2"
    )
    assert template_path.exists(), f"Template not found: {template_path}"
    raw = template_path.read_text(encoding="utf-8")

    jinja_stripped = re.sub(r"\{[{%#].*?[}%#]\}", "", raw, flags=re.DOTALL)

    assert not re.search(r"max_steps\s*[=:]\s*\d+", jinja_stripped), (
        "Found a bare integer literal adjacent to 'max_steps' in the static "
        "(non-Jinja) text of graph_agent.py.j2. Use {{ react_max_steps }} instead."
    )


def test_react_graph_agent_template_contains_no_hardcoded_temperature() -> None:
    """The graph_agent.py.j2 template must not contain bare integers adjacent to temperature."""
    template_path = (
        Path(__file__).parent.parent.parent
        / "agentforge"
        / "templates"
        / "patterns"
        / "react"
        / "graph_agent.py.j2"
    )
    assert template_path.exists(), f"Template not found: {template_path}"
    raw = template_path.read_text(encoding="utf-8")

    jinja_stripped = re.sub(r"\{[{%#].*?[}%#]\}", "", raw, flags=re.DOTALL)

    assert not re.search(r"temperature\s*=\s*\d", jinja_stripped), (
        "Found a bare integer literal adjacent to 'temperature' in the static "
        "(non-Jinja) text of graph_agent.py.j2. Use {{ react_temperature }} instead."
    )


# ── graph_agent.py presence/absence by pattern ───────────────────────────────


def test_graph_agent_present_for_react() -> None:
    """backend/graph/graph_agent.py must be rendered when pattern=react."""
    config = _make_react_config()
    rendered = _render_map(config)
    assert "backend/graph/graph_agent.py" in rendered, (
        "backend/graph/graph_agent.py must be emitted for react-pattern projects"
    )


def test_graph_agent_absent_for_orchestrator() -> None:
    """backend/graph/graph_agent.py must NOT be rendered for legacy orchestrator projects."""
    config = _make_orchestrator_config()
    rendered = _render_map(config)
    assert "backend/graph/graph_agent.py" not in rendered, (
        "backend/graph/graph_agent.py must be absent for orchestrator-pattern projects"
    )


# ── Orchestrator single-invoke behavior preserved ─────────────────────────────


def test_orchestrator_agent_uses_single_invoke() -> None:
    """Legacy orchestrator agent.py must still contain the single llm.invoke() call.

    This confirms the shared template is untouched and the react overlay does
    not bleed into orchestrator renders.
    """
    config = _make_orchestrator_config()
    rendered = _render_map(config)
    source = rendered["backend/agents/sql_agent.py"]

    # The shared (orchestrator) template contains the stub comment.
    assert "single-shot LLM call" in source, (
        "Orchestrator agent.py must still use the single-shot LLM call stub"
    )
    # Must NOT contain the ReAct StateGraph wiring.
    assert "StateGraph" not in source, (
        "Orchestrator agent.py must not contain StateGraph — react overlay must not bleed through"
    )


# ── No Madgicx strings ────────────────────────────────────────────────────────


@pytest.mark.parametrize("max_steps", [3, 12])
@pytest.mark.parametrize("tool_choice", ["auto", "required"])
def test_no_madgicx_strings_in_react_render(max_steps: int, tool_choice: str) -> None:
    """No rendered file for a react project must contain 'madgicx' (case-insensitive)."""
    config = _make_react_config(max_steps=max_steps, tool_choice=tool_choice)
    rendered = _render_map(config)
    violations = [
        path for path, content in rendered.items() if "madgicx" in content.lower()
    ]
    assert not violations, (
        f"'madgicx' found in rendered files for react pattern: {violations}"
    )
