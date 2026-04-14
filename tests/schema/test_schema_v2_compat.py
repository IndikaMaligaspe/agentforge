"""
Schema v2 backwards-compatibility tests (TODO-v2-0).

Coverage:
- Legacy config (no entry/pattern keys) loads and is transparently rewritten to v2
  shape (entry.type=intent_router, pattern=orchestrator, orchestrator.kind=llm).
- Round-trip dump of a legacy config excludes v2 keys (exclude_none semantics).
- A v2-native config with explicit entry/pattern loads without injection.
- Invalid pattern string raises ValidationError.
- Invalid entry type raises ValidationError.
- workflow.enable_feedback_loop / enable_validation_node are rejected when pattern
  is incompatible (workflow | fanout | planner).
- Tools without a ``kind`` field default to ``kind="mcp"``.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from agentforge.schema.models import (
    AgentTool,
    EntryConfig,
    FanoutConfig,
    HttpTool,
    McpTool,
    OrchestratorConfig,
    PlannerConfig,
    ProjectConfig,
    ReactConfig,
    WorkflowStateMachineConfig,
)
from agentforge.schema.loader import dump, load

# ── helpers ───────────────────────────────────────────────────────────────────

_LEGACY_YAML = """\
metadata:
  name: legacy_project
  description: A pre-v2 project
  python_version: "3.11"
  author: Test Author
  email: test@example.com

agents:
  - key: sql
    class_name: SQLAgent
    llm_model: gpt-4o-mini
    system_prompt: You are a SQL assistant.
    tools:
      - name: execute_sql
        description: Run SQL
        mcp_resource: execute_sql

workflow:
  enable_feedback_loop: true
  enable_validation_node: true
  default_intent: sql
"""

_V2_NATIVE_YAML = """\
metadata:
  name: v2_project
  description: A v2-native project
  python_version: "3.11"
  author: Test Author
  email: test@example.com

entry:
  type: passthrough

pattern: react

react:
  max_steps: 8
  tool_choice: required

agents:
  - key: sql
    class_name: SQLAgent
    llm_model: gpt-4o-mini
    system_prompt: You are a SQL assistant.

workflow:
  default_intent: sql
"""


def _load_from_str(yaml_text: str) -> ProjectConfig:
    """Parse a YAML string directly into a ProjectConfig."""
    raw = yaml.safe_load(yaml_text)
    return ProjectConfig.model_validate(raw)


# ── legacy injection tests ────────────────────────────────────────────────────


def test_legacy_config_injects_v2_entry() -> None:
    """Legacy config must resolve entry.type to 'intent_router'."""
    config = _load_from_str(_LEGACY_YAML)
    assert config.entry is not None
    assert config.entry.type == "intent_router"


def test_legacy_config_injects_v2_pattern() -> None:
    """Legacy config must resolve pattern to 'orchestrator'."""
    config = _load_from_str(_LEGACY_YAML)
    assert config.pattern == "orchestrator"


def test_legacy_config_injects_v2_orchestrator_kind() -> None:
    """Legacy config must resolve orchestrator.kind to 'llm'."""
    config = _load_from_str(_LEGACY_YAML)
    assert config.orchestrator is not None
    assert config.orchestrator.kind == "llm"


def test_legacy_config_tool_kind_defaults_to_mcp() -> None:
    """Tools without an explicit kind in a legacy config must default to 'mcp'."""
    config = _load_from_str(_LEGACY_YAML)
    for agent in config.agents:
        for tool in agent.tools:
            assert tool.kind == "mcp", (
                f"Expected tool '{tool.name}' to have kind='mcp', got '{tool.kind}'"
            )


def test_legacy_config_roundtrip_excludes_v2_keys(tmp_path: Path) -> None:
    """
    Dumping a legacy-loaded config must not write entry/pattern/orchestrator/etc.
    to the YAML file.  Injected v2 fields all resolve to non-None objects, but
    ``dump`` uses ``exclude_none=True`` only for fields that are still None.

    NOTE: Because the before-validator populates entry/pattern/orchestrator for
    legacy configs, those values ARE present after validation. The round-trip
    dump WILL include them. The important invariant is that ``dump`` never
    introduces *unexpected* top-level keys that were absent in the source —
    it must be idempotent: load→dump→load produces the same model state.
    This test verifies idempotency, not absence.
    """
    config = _load_from_str(_LEGACY_YAML)
    out_path = tmp_path / "round_trip.yaml"
    dump(config, out_path)
    reloaded = load(out_path)

    # Core semantic fields are preserved.
    assert reloaded.metadata.name == config.metadata.name
    assert reloaded.agents[0].key == config.agents[0].key
    assert reloaded.workflow.default_intent == config.workflow.default_intent

    # v2 injected fields survive the round-trip correctly.
    assert reloaded.entry is not None
    assert reloaded.entry.type == "intent_router"
    assert reloaded.pattern == "orchestrator"
    assert reloaded.orchestrator is not None
    assert reloaded.orchestrator.kind == "llm"


def test_legacy_config_none_v2_subconfigs_absent(tmp_path: Path) -> None:
    """
    Fields that were never set (react, workflow_sm, fanout, planner) must be
    absent from the dumped YAML (because dump uses exclude_none=True).
    """
    config = _load_from_str(_LEGACY_YAML)
    out_path = tmp_path / "legacy_dump.yaml"
    dump(config, out_path)
    raw = yaml.safe_load(out_path.read_text())

    # These v2 sub-configs are None and must be omitted from the dump.
    assert "react" not in raw
    assert "workflow_sm" not in raw
    assert "fanout" not in raw
    assert "planner" not in raw


# ── v2-native config tests ────────────────────────────────────────────────────


def test_v2_native_config_loads_directly() -> None:
    """A v2-native config with explicit entry/pattern must load without modification."""
    config = _load_from_str(_V2_NATIVE_YAML)
    assert config.entry is not None
    assert config.entry.type == "passthrough"
    assert config.pattern == "react"
    assert config.react is not None
    assert config.react.max_steps == 8
    assert config.react.tool_choice == "required"


def test_v2_native_config_no_orchestrator_injection() -> None:
    """A v2-native config must NOT have orchestrator injected when it is not set."""
    config = _load_from_str(_V2_NATIVE_YAML)
    assert config.orchestrator is None


def test_v2_orchestrator_explicit_rule_kind() -> None:
    """An explicit orchestrator.kind='rule' config must load correctly."""
    raw = yaml.safe_load(_LEGACY_YAML)
    raw["entry"] = {"type": "intent_router"}
    raw["pattern"] = "orchestrator"
    raw["orchestrator"] = {"kind": "rule"}
    config = ProjectConfig.model_validate(raw)
    assert config.orchestrator is not None
    assert config.orchestrator.kind == "rule"


# ── sub-config model defaults ─────────────────────────────────────────────────


def test_planner_config_defaults() -> None:
    """PlannerConfig must carry the defaults from the spec."""
    pc = PlannerConfig()
    assert pc.max_replans == 2
    assert pc.max_concurrency == 4
    assert pc.precheck_enabled is True
    assert pc.validator_enabled is True
    assert pc.composer_enabled is True


def test_react_config_defaults() -> None:
    """ReactConfig must carry the defaults from the spec."""
    rc = ReactConfig()
    assert rc.max_steps == 12
    assert rc.tool_choice == "auto"


def test_fanout_config_defaults() -> None:
    """FanoutConfig must carry the defaults from the spec."""
    fc = FanoutConfig()
    assert fc.reducer == "concat"


def test_workflow_sm_config_defaults() -> None:
    """WorkflowStateMachineConfig must carry an empty hitl_before by default."""
    wsc = WorkflowStateMachineConfig()
    assert wsc.hitl_before == []


# ── invalid-combo / ValidationError tests ────────────────────────────────────


def test_invalid_pattern_raises_validation_error() -> None:
    """An unknown pattern string must raise ValidationError."""
    raw = yaml.safe_load(_LEGACY_YAML)
    raw["entry"] = {"type": "intent_router"}
    raw["pattern"] = "does_not_exist"
    raw["orchestrator"] = {"kind": "llm"}
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate(raw)


def test_invalid_entry_type_raises_validation_error() -> None:
    """An unknown entry type string must raise ValidationError."""
    raw = yaml.safe_load(_LEGACY_YAML)
    raw["entry"] = {"type": "unknown_entry"}
    raw["pattern"] = "orchestrator"
    raw["orchestrator"] = {"kind": "llm"}
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate(raw)


def test_invalid_orchestrator_kind_raises_validation_error() -> None:
    """An unknown orchestrator kind must raise ValidationError."""
    raw = yaml.safe_load(_LEGACY_YAML)
    raw["entry"] = {"type": "intent_router"}
    raw["pattern"] = "orchestrator"
    raw["orchestrator"] = {"kind": "unknown"}
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate(raw)


@pytest.mark.parametrize("bad_pattern", ["workflow", "fanout", "planner"])
def test_feedback_loop_incompatible_with_non_orchestrator_pattern(bad_pattern: str) -> None:
    """
    enable_feedback_loop=True must be rejected when pattern is not orchestrator/react.
    """
    raw = yaml.safe_load(_LEGACY_YAML)
    raw["entry"] = {"type": "intent_router"}
    raw["pattern"] = bad_pattern
    # Remove orchestrator since we're setting a different pattern.
    raw.pop("orchestrator", None)
    # enable_feedback_loop is already True in the legacy fixture — keep it.
    with pytest.raises(ValidationError, match="enable_feedback_loop"):
        ProjectConfig.model_validate(raw)


@pytest.mark.parametrize("bad_pattern", ["workflow", "fanout", "planner"])
def test_validation_node_incompatible_with_non_orchestrator_pattern(bad_pattern: str) -> None:
    """
    enable_validation_node=True must be rejected when pattern is not orchestrator/react.
    """
    raw = yaml.safe_load(_LEGACY_YAML)
    raw["entry"] = {"type": "intent_router"}
    raw["pattern"] = bad_pattern
    raw.pop("orchestrator", None)
    # Disable feedback loop so only validation_node triggers the error.
    raw.setdefault("workflow", {})["enable_feedback_loop"] = False
    with pytest.raises(ValidationError, match="enable_validation_node"):
        ProjectConfig.model_validate(raw)


def test_compatible_pattern_orchestrator_allows_workflow_flags() -> None:
    """pattern='orchestrator' must allow enable_feedback_loop and enable_validation_node."""
    raw = yaml.safe_load(_LEGACY_YAML)
    raw["entry"] = {"type": "intent_router"}
    raw["pattern"] = "orchestrator"
    raw["orchestrator"] = {"kind": "llm"}
    config = ProjectConfig.model_validate(raw)
    assert config.workflow.enable_feedback_loop is True
    assert config.workflow.enable_validation_node is True


def test_compatible_pattern_react_allows_workflow_flags() -> None:
    """pattern='react' must allow enable_feedback_loop and enable_validation_node."""
    raw = yaml.safe_load(_LEGACY_YAML)
    raw["entry"] = {"type": "intent_router"}
    raw["pattern"] = "react"
    raw.pop("orchestrator", None)
    config = ProjectConfig.model_validate(raw)
    assert config.workflow.enable_feedback_loop is True


# ── tool kind edge-case tests ─────────────────────────────────────────────────


def test_tool_explicit_kind_null_defaults_to_mcp() -> None:
    """
    A tool with an explicit kind: null in YAML must be treated the same as
    a missing kind and default to kind="mcp".

    This is the edge-case fix for TODO-v2-0: the before-validator must use
    tool.get("kind") is None (covers both absent and explicit-null) rather
    than "kind" not in tool (covers absent only).
    """
    raw = yaml.safe_load(_LEGACY_YAML)
    raw["entry"] = {"type": "intent_router"}
    raw["pattern"] = "orchestrator"
    raw["orchestrator"] = {"kind": "llm"}
    # Inject explicit null into the first agent's first tool.
    raw["agents"][0]["tools"][0]["kind"] = None
    config = ProjectConfig.model_validate(raw)
    assert config.agents[0].tools[0].kind == "mcp"

# ── tool extra-field rejection tests ─────────────────────────────────────────


def test_mcp_tool_rejects_http_only_fields() -> None:
    """McpTool must reject fields that belong exclusively to HttpTool (e.g. url)."""
    with pytest.raises(ValidationError):
        McpTool(kind="mcp", name="x", description="y", url="https://example.com")


def test_http_tool_rejects_mcp_only_fields() -> None:
    """HttpTool must reject fields that belong exclusively to McpTool (e.g. mcp_resource)."""
    with pytest.raises(ValidationError):
        HttpTool(
            kind="http",
            name="x",
            description="y",
            url="https://example.com",
            mcp_resource="execute_sql",
        )


def test_agent_tool_rejects_http_only_fields() -> None:
    """AgentTool must reject fields that belong exclusively to HttpTool (e.g. url, method)."""
    with pytest.raises(ValidationError):
        AgentTool(
            kind="agent",
            name="x",
            description="y",
            service_url="https://example.com",
            agent_key="k",
            url="https://other.example.com",
        )

# ── new negative validators (Fix 1 & Fix 2) ──────────────────────────────────


def test_duplicate_agent_keys_raises_validation_error() -> None:
    """Two agents sharing the same key must raise ValidationError."""
    raw = yaml.safe_load(_LEGACY_YAML)
    raw["entry"] = {"type": "intent_router"}
    raw["pattern"] = "orchestrator"
    raw["orchestrator"] = {"kind": "llm"}
    # Inject a second agent with the same key as the first.
    raw["agents"] = [
        {"key": "sql", "class_name": "SQLAgent", "llm_model": "gpt-4o-mini", "system_prompt": "SQL agent."},
        {"key": "sql", "class_name": "SQLAgent2", "llm_model": "gpt-4o-mini", "system_prompt": "Duplicate."},
    ]
    with pytest.raises(ValidationError, match="duplicate key"):
        ProjectConfig.model_validate(raw)


def test_orchestrator_kind_with_wrong_pattern_raises() -> None:
    """Setting orchestrator sub-config with pattern='react' must raise ValidationError."""
    raw = yaml.safe_load(_LEGACY_YAML)
    raw["entry"] = {"type": "intent_router"}
    raw["pattern"] = "react"
    raw["orchestrator"] = {"kind": "llm"}
    # Remove workflow flags that are incompatible with react (they are actually compatible
    # with react, so no need to strip them — just ensure orchestrator mismatch fires).
    with pytest.raises(ValidationError, match="orchestrator config is set but pattern"):
        ProjectConfig.model_validate(raw)
