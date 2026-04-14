"""
tests/test_campaign_health_v2.py — Topology assertions for v2-native CHS and copilot fixtures.

These fixtures are test-grade: hand-authored directly against the v2 schema with no
reliance on the legacy-compat shim.  They exercise v2-native paths to prove the schema
can express the real Campaign Health Score topology with zero workarounds.

Scope
-----
Parametrized over two fixtures in tests/fixtures/:
  - campaign_health_v2.yaml  (orchestrator pattern, rule kind, 4 agents)
  - copilot_v2.yaml          (react pattern, passthrough entry, 1 agent, JWT auth)

Common checks (both fixtures):
  1. Config loads via schema.loader.load without ValidationError.
  2. Renderer produces a non-empty tree; every .py file compiles via compile(src, path, "exec").
  3. No forbidden strings in any generated file (imported from tests/e2e/conftest.py).

CHS-specific topology assertions (campaign_health_v2 only):
  4. backend/graph/nodes/query_router_node.py is present (intent_router entry node).
  5. backend/graph/nodes/supervisor_node.py does NOT contain ChatOpenAI (rule-based dispatch,
     not LLM-based); confirms pure Python orchestration.
  6. All 4 CHS agent keys referenced in backend/agents/registry.py.
  7. All 4 agent files exist at backend/agents/<key>_agent.py.
  8. backend/graph/checkpointer.py is present (workflow.enable_checkpointing=true triggers
     the AsyncPostgresSaver path).

Copilot-specific topology assertions (copilot_v2 only):
  9. backend/graph/nodes/passthrough_node.py is present (entry.type=passthrough).
 10. backend/graph/graph_agent.py contains StateGraph and add_conditional_edges (ReAct loop).
 11. backend/security/jwt.py is present (security.auth_type=jwt).
 12. backend/services/agent_tool.py is present (agent-kind tool in the copilot config).

Design decisions
----------------
- render_yaml_to_dict and FORBIDDEN_STRINGS are imported from tests/e2e/conftest.py to avoid
  duplication with test_v2_patterns.py.
- Parametrization uses the fixture filename stem as test ID for readable output.
- Topology assertions are fixture-specific and selected via pytest.mark.parametrize
  on the fixture name — no broad conditionals inside a single test function.
- compile() (not ast.parse()) is used for .py validation: it catches bytecode-generation
  errors that ast.parse() silently passes.
"""
from __future__ import annotations

import re
import warnings
from pathlib import Path

import pytest

from tests.e2e.conftest import FORBIDDEN_STRINGS, render_yaml_to_dict

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FIXTURES_DIR: Path = Path(__file__).parent / "fixtures"

# Both v2-native fixtures.  Parametrize IDs are the bare stem.
_FIXTURE_FILES = [
    "campaign_health_v2.yaml",
    "copilot_v2.yaml",
]
_FIXTURE_IDS = [Path(f).stem for f in _FIXTURE_FILES]

# The 4 CHS agent keys — single source of truth for all assertions below.
_CHS_AGENT_KEYS: list[str] = [
    "campaign_scorer",
    "insight_enricher",
    "synthesizer",
    "output_formatter",
]


# ---------------------------------------------------------------------------
# Module-scoped render fixture — render each yaml once, share across tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", params=_FIXTURE_FILES, ids=_FIXTURE_IDS)
def v2_fixture_rendered(
    request: pytest.FixtureRequest,
) -> tuple[str, dict[str, str]]:
    """
    Module-scoped fixture: renders one v2 test fixture yaml and returns
    ``(bare_stem, {rel_path: content})``.

    Module scope is intentional — rendering is the expensive step, and all
    test functions for a given fixture share the same in-memory output.
    """
    filename: str = request.param
    stem = Path(filename).stem
    rendered = render_yaml_to_dict(_FIXTURES_DIR / filename)
    return stem, rendered


# ---------------------------------------------------------------------------
# Common checks — both fixtures
# ---------------------------------------------------------------------------


def test_v2_fixture_loads_without_error(v2_fixture_rendered: tuple[str, dict[str, str]]) -> None:
    """
    Config must load and validate successfully.

    render_yaml_to_dict calls schema.loader.load internally; any ValidationError
    or schema-loading exception propagates as a test failure here.
    """
    stem, rendered = v2_fixture_rendered
    assert rendered, f"Fixture '{stem}': render produced no output"


def test_v2_fixture_all_py_compile(v2_fixture_rendered: tuple[str, dict[str, str]]) -> None:
    """
    compile(src, path, "exec") must succeed for every generated .py file.

    compile() is stricter than ast.parse() — it also catches bytecode-generation
    issues such as duplicate argument names and invalid augmented assignments.
    """
    stem, rendered = v2_fixture_rendered
    failures: list[str] = []
    for rel_path, content in sorted(rendered.items()):
        if not rel_path.endswith(".py"):
            continue
        try:
            compile(content, rel_path, "exec")
        except SyntaxError as exc:
            failures.append(f"  {rel_path}: {exc}")

    assert not failures, (
        f"Fixture '{stem}': generated .py files failed compile():\n"
        + "\n".join(failures)
    )


def test_v2_fixture_no_forbidden_strings(
    v2_fixture_rendered: tuple[str, dict[str, str]],
) -> None:
    """
    No generated file may contain any string from FORBIDDEN_STRINGS
    (imported from tests/e2e/conftest.py — not redefined here).
    """
    stem, rendered = v2_fixture_rendered
    violations: list[str] = []
    for rel_path, content in sorted(rendered.items()):
        for forbidden in FORBIDDEN_STRINGS:
            if re.search(forbidden, content, re.IGNORECASE):
                violations.append(f"  {rel_path}: contains '{forbidden}'")

    assert not violations, (
        f"Fixture '{stem}': forbidden strings found in scaffold:\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# CHS-specific topology assertions — campaign_health_v2 only
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def chs_rendered(request: pytest.FixtureRequest) -> dict[str, str]:
    """Render campaign_health_v2.yaml once for all CHS-specific tests."""
    return render_yaml_to_dict(_FIXTURES_DIR / "campaign_health_v2.yaml")


def test_chs_intent_router_node_present(chs_rendered: dict[str, str]) -> None:
    """
    entry.type=intent_router must produce backend/graph/nodes/query_router_node.py.

    This is the LLM-based intent classification node that parses free-text queries
    and routes to an agent key.  Its presence confirms the intent_router entry path
    was rendered rather than the passthrough or direct paths.
    """
    assert "backend/graph/nodes/query_router_node.py" in chs_rendered, (
        "CHS fixture: backend/graph/nodes/query_router_node.py not found in scaffold. "
        "This is required for entry.type=intent_router."
    )


def test_chs_rule_based_supervisor_no_llm(chs_rendered: dict[str, str]) -> None:
    """
    orchestrator.kind=rule must produce a supervisor_node that dispatches via
    pure Python (not an LLM call).

    The rule-based supervisor looks up state['intent'] in AgentRegistry and calls
    agent.run() directly — no ChatOpenAI / ChatAnthropic instantiation.  Asserting
    the absence of 'ChatOpenAI' in the supervisor confirms the rule-based codegen
    path ran rather than the llm-kind path.
    """
    supervisor_path = "backend/graph/nodes/supervisor_node.py"
    assert supervisor_path in chs_rendered, (
        f"CHS fixture: {supervisor_path} not found in scaffold."
    )
    supervisor_content = chs_rendered[supervisor_path]
    assert "ChatOpenAI" not in supervisor_content, (
        f"CHS fixture: {supervisor_path} contains 'ChatOpenAI' — "
        "orchestrator.kind=rule should produce a pure Python dispatcher, "
        "not an LLM-based supervisor."
    )


def test_chs_supervisor_references_agent_keys(chs_rendered: dict[str, str]) -> None:
    """
    The registry.py (which the supervisor uses for dispatch) must reference all 4
    CHS agent keys — confirming the rule-based orchestrator topology was fully rendered
    with all four declared agents.
    """
    registry_path = "backend/agents/registry.py"
    assert registry_path in chs_rendered, (
        f"CHS fixture: {registry_path} not found in scaffold."
    )
    registry_content = chs_rendered[registry_path]
    missing_keys = [k for k in _CHS_AGENT_KEYS if k not in registry_content]
    assert not missing_keys, (
        f"CHS fixture: {registry_path} is missing agent key(s): {missing_keys}. "
        f"All 4 CHS agent keys must be registered: {_CHS_AGENT_KEYS}."
    )


def test_chs_all_agent_files_present(chs_rendered: dict[str, str]) -> None:
    """
    Each of the 4 CHS agents must produce a scaffolded agent file at
    backend/agents/<key>_agent.py.
    """
    missing_files = [
        f"backend/agents/{key}_agent.py"
        for key in _CHS_AGENT_KEYS
        if f"backend/agents/{key}_agent.py" not in chs_rendered
    ]
    assert not missing_files, (
        f"CHS fixture: the following agent files are missing from the scaffold:\n"
        + "\n".join(f"  {f}" for f in missing_files)
    )


def test_chs_checkpointer_present(chs_rendered: dict[str, str]) -> None:
    """
    workflow.enable_checkpointing=true + database.backend=postgres must produce
    backend/graph/checkpointer.py (the AsyncPostgresSaver wiring module).

    The checkpointer module is only emitted when checkpointing is enabled — its
    presence confirms the LangGraph PostgresSaver codegen path was triggered.
    """
    assert "backend/graph/checkpointer.py" in chs_rendered, (
        "CHS fixture: backend/graph/checkpointer.py not found in scaffold. "
        "workflow.enable_checkpointing=true should trigger the AsyncPostgresSaver path."
    )


# ---------------------------------------------------------------------------
# Copilot-specific topology assertions — copilot_v2 only
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def copilot_rendered(request: pytest.FixtureRequest) -> dict[str, str]:
    """Render copilot_v2.yaml once for all copilot-specific tests."""
    return render_yaml_to_dict(_FIXTURES_DIR / "copilot_v2.yaml")


def test_copilot_passthrough_node_present(copilot_rendered: dict[str, str]) -> None:
    """
    entry.type=passthrough must produce backend/graph/nodes/passthrough_node.py.

    This node is only generated for passthrough entry configs — its presence
    confirms that the v2-native passthrough path (caller supplies intent; LLM
    only extracts structured inputs) was rendered correctly.
    """
    assert "backend/graph/nodes/passthrough_node.py" in copilot_rendered, (
        "Copilot fixture: backend/graph/nodes/passthrough_node.py not found in scaffold. "
        "This is required for entry.type=passthrough."
    )


def test_copilot_react_loop_structure(copilot_rendered: dict[str, str]) -> None:
    """
    pattern=react must produce a backend/graph/graph_agent.py that contains
    a real ReAct loop: StateGraph with both 'agent' and 'tools' nodes connected
    via a conditional edge back to the agent node.

    StateGraph confirms the graph is LangGraph-backed.
    add_conditional_edges confirms the tool-call loop conditional routing is wired
    (agent → tools → agent cycle, terminating on finish_reason='stop').
    """
    graph_agent_path = "backend/graph/graph_agent.py"
    assert graph_agent_path in copilot_rendered, (
        f"Copilot fixture: {graph_agent_path} not found in scaffold. "
        "pattern=react should produce a ReAct graph_agent module."
    )
    graph_agent_content = copilot_rendered[graph_agent_path]

    assert "StateGraph" in graph_agent_content, (
        f"Copilot fixture: {graph_agent_path} does not contain 'StateGraph'. "
        "The ReAct graph must use a LangGraph StateGraph."
    )
    assert "add_conditional_edges" in graph_agent_content, (
        f"Copilot fixture: {graph_agent_path} does not contain 'add_conditional_edges'. "
        "The ReAct loop requires a conditional edge for the agent ↔ tools cycle."
    )


def test_copilot_jwt_verifier_present(copilot_rendered: dict[str, str]) -> None:
    """
    security.auth_type=jwt must produce backend/security/jwt.py.

    This file wires the JWT verification logic (JWKS fetch, token decode, claims
    validation).  Its presence confirms the JWT auth codegen path was triggered.
    """
    assert "backend/security/jwt.py" in copilot_rendered, (
        "Copilot fixture: backend/security/jwt.py not found in scaffold. "
        "security.auth_type=jwt should produce the JWT verifier module."
    )


def test_copilot_agent_tool_service_present(copilot_rendered: dict[str, str]) -> None:
    """
    An agent-kind tool in the copilot config must produce backend/services/agent_tool.py.

    This service module provides the cross-service HTTP call that delegates to a
    downstream AgentForge service (campaign_health) via JWT-authenticated HTTP.
    Its presence confirms the agent tool-kind codegen path was triggered.
    """
    assert "backend/services/agent_tool.py" in copilot_rendered, (
        "Copilot fixture: backend/services/agent_tool.py not found in scaffold. "
        "An agent-kind tool should produce the agent_tool service module."
    )


def test_copilot_no_intent_router_node(copilot_rendered: dict[str, str]) -> None:
    """entry.type=passthrough must NOT emit the intent_router query_router_node."""
    assert "backend/graph/nodes/query_router_node.py" not in copilot_rendered, (
        "Copilot fixture: query_router_node.py must not be rendered when "
        "entry.type=passthrough. Its presence indicates entry-type gating leaked."
    )


def test_chs_no_react_graph_agent(chs_rendered: dict[str, str]) -> None:
    """pattern=orchestrator must NOT emit the react pattern's graph_agent.py."""
    assert "backend/graph/graph_agent.py" not in chs_rendered, (
        "CHS fixture: graph_agent.py must not be rendered for "
        "pattern=orchestrator. Its presence indicates pattern gating leaked."
    )
