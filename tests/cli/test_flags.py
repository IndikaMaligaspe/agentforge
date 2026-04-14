"""
Tests for the CLI flags translator and end-to-end flag-driven init command.

Coverage:
- Pure ``flags_to_config_patch`` function — every flag, every combination.
- End-to-end via Typer's CliRunner: valid configs, mutual exclusion errors,
  invalid enum values, and the acceptance scenario from TODO-v2-8.
- Round-trip property: every valid flag combination produces a config that
  round-trips through dump/load unchanged.
"""
from __future__ import annotations

import pathlib
import pytest
import yaml

from typer.testing import CliRunner

from agentforge.cli.app import app
from agentforge.cli.flags import (
    ENTRY_TYPE_CHOICES,
    ORCHESTRATOR_KIND_CHOICES,
    PATTERN_CHOICES,
    parse_agents,
    _to_class_name,
    flags_to_config_patch,
)
from agentforge.schema.loader import load


# ── Fixtures / helpers ────────────────────────────────────────────────────────

runner = CliRunner(mix_stderr=False)


def _invoke_init(args: list[str]) -> object:
    """Invoke ``agentforge init`` with *args* via the test runner."""
    return runner.invoke(app, ["init"] + args)


# ── Unit tests: pure helper functions ─────────────────────────────────────────

class TestToClassName:
    def test_simple_key(self):
        assert _to_class_name("alpha") == "AlphaAgent"

    def test_multi_word_key(self):
        assert _to_class_name("my_bot") == "MyBotAgent"

    def test_single_char(self):
        assert _to_class_name("a") == "AAgent"

    def test_preserves_existing_case_in_parts(self):
        # Input keys are lowercase by schema constraint; capitalise() is applied.
        assert _to_class_name("sql") == "SqlAgent"


class TestParseAgents:
    def test_none_returns_empty(self):
        assert parse_agents(None) == []

    def test_empty_string_returns_empty(self):
        assert parse_agents("") == []

    def test_single_agent(self):
        result = parse_agents("alpha")
        assert result == [{"key": "alpha", "class_name": "AlphaAgent"}]

    def test_multiple_agents(self):
        result = parse_agents("alpha,beta,gamma")
        assert len(result) == 3
        assert result[0] == {"key": "alpha", "class_name": "AlphaAgent"}
        assert result[1] == {"key": "beta", "class_name": "BetaAgent"}
        assert result[2] == {"key": "gamma", "class_name": "GammaAgent"}

    def test_whitespace_stripped(self):
        result = parse_agents(" alpha , beta ")
        assert result[0]["key"] == "alpha"
        assert result[1]["key"] == "beta"

    def test_empty_segments_skipped(self):
        result = parse_agents("alpha,,beta")
        assert len(result) == 2


# ── Unit tests: flags_to_config_patch ─────────────────────────────────────────

class TestFlagsToConfigPatch:
    """Pure-function tests covering every flag and combination."""

    # ── No flags ──────────────────────────────────────────────────────────────

    def test_no_flags_returns_empty_patch(self):
        patch = flags_to_config_patch()
        assert patch == {}

    # ── Entry type ────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("entry_type", list(ENTRY_TYPE_CHOICES))
    def test_entry_type_set(self, entry_type):
        patch = flags_to_config_patch(entry_type=entry_type)
        assert patch["entry"] == {"type": entry_type}
        assert "pattern" not in patch

    # ── Pattern ───────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("pattern", list(PATTERN_CHOICES))
    def test_pattern_set(self, pattern):
        patch = flags_to_config_patch(pattern=pattern)
        assert patch["pattern"] == pattern
        assert "entry" not in patch

    # ── Orchestrator kind ─────────────────────────────────────────────────────

    @pytest.mark.parametrize("kind", list(ORCHESTRATOR_KIND_CHOICES))
    def test_orchestrator_kind(self, kind):
        patch = flags_to_config_patch(orchestrator_kind=kind)
        assert patch["orchestrator"] == {"kind": kind}

    # ── Agents CSV ────────────────────────────────────────────────────────────

    def test_agents_single(self):
        patch = flags_to_config_patch(agents_csv="alpha")
        assert len(patch["agents"]) == 1
        assert patch["agents"][0]["key"] == "alpha"
        assert patch["agents"][0]["class_name"] == "AlphaAgent"

    def test_agents_multiple(self):
        patch = flags_to_config_patch(agents_csv="alpha,beta")
        assert len(patch["agents"]) == 2

    def test_agents_keys_correct(self):
        patch = flags_to_config_patch(agents_csv="my_bot,sql_engine")
        assert patch["agents"][0]["class_name"] == "MyBotAgent"
        assert patch["agents"][1]["class_name"] == "SqlEngineAgent"

    # ── Tool flags ────────────────────────────────────────────────────────────

    def test_mcp_tool_no_agents(self):
        """When no --agents, tools surfaced at patch root under 'tools'."""
        patch = flags_to_config_patch(mcp_tools=["my_mcp"])
        assert "tools" in patch
        assert patch["tools"][0]["kind"] == "mcp"
        assert patch["tools"][0]["name"] == "my_mcp"

    def test_http_tool_no_agents(self):
        patch = flags_to_config_patch(http_tools=["my_http"])
        assert patch["tools"][0]["kind"] == "http"
        assert "url" in patch["tools"][0]

    def test_agent_tool_no_agents(self):
        patch = flags_to_config_patch(agent_tools=["downstream"])
        assert patch["tools"][0]["kind"] == "agent"
        assert "service_url" in patch["tools"][0]
        assert patch["tools"][0]["agent_key"] == "downstream"

    def test_multiple_mcp_tools_no_agents(self):
        """Multiple --mcp flags all appear as separate tools."""
        patch = flags_to_config_patch(mcp_tools=["foo", "bar"])
        tool_names = [t["name"] for t in patch["tools"]]
        assert "foo" in tool_names
        assert "bar" in tool_names

    def test_tools_attached_to_agents_when_agents_given(self):
        """When --agents is given, tools are attached to each agent."""
        patch = flags_to_config_patch(
            agents_csv="alpha,beta",
            mcp_tools=["foo"],
            http_tools=["bar"],
        )
        assert "tools" not in patch  # no root-level tools key
        for agent in patch["agents"]:
            tool_names = {t["name"] for t in agent["tools"]}
            assert "foo" in tool_names
            assert "bar" in tool_names

    def test_mixed_tool_kinds_with_agents(self):
        patch = flags_to_config_patch(
            agents_csv="alpha",
            mcp_tools=["mcp_tool"],
            http_tools=["http_tool"],
            agent_tools=["agent_tool"],
        )
        tools = patch["agents"][0]["tools"]
        kinds = {t["kind"] for t in tools}
        assert kinds == {"mcp", "http", "agent"}

    # ── Combined flags ────────────────────────────────────────────────────────

    def test_combined_entry_and_pattern(self):
        patch = flags_to_config_patch(
            entry_type="passthrough",
            pattern="react",
        )
        assert patch["entry"] == {"type": "passthrough"}
        assert patch["pattern"] == "react"

    def test_full_combination(self):
        patch = flags_to_config_patch(
            entry_type="intent_router",
            pattern="orchestrator",
            orchestrator_kind="rule",
            agents_csv="alpha,beta",
            mcp_tools=["foo"],
            http_tools=["bar"],
            agent_tools=["downstream"],
        )
        assert patch["entry"]["type"] == "intent_router"
        assert patch["pattern"] == "orchestrator"
        assert patch["orchestrator"]["kind"] == "rule"
        assert len(patch["agents"]) == 2
        # All 3 tool kinds attached to each agent
        for agent in patch["agents"]:
            assert len(agent["tools"]) == 3

    def test_patch_omits_unset_keys(self):
        """Unset flags must not appear as None keys in the patch."""
        patch = flags_to_config_patch(pattern="planner")
        assert "entry" not in patch
        assert "orchestrator" not in patch
        assert "agents" not in patch
        assert "tools" not in patch

    # ── Choices sourced from schema constants ─────────────────────────────────

    def test_pattern_choices_match_schema(self):
        """PATTERN_CHOICES must include every value from _PATTERN_LITERALS."""
        from typing import get_args
        from agentforge.schema.models import _PATTERN_LITERALS
        assert set(PATTERN_CHOICES) == set(get_args(_PATTERN_LITERALS))

    def test_entry_type_choices_match_schema(self):
        from typing import get_args
        from agentforge.schema.models import _ENTRY_TYPE_LITERALS
        assert set(ENTRY_TYPE_CHOICES) == set(get_args(_ENTRY_TYPE_LITERALS))


# ── End-to-end CLI tests ──────────────────────────────────────────────────────

class TestInitCLIFlagDriven:
    """Typer CliRunner-based tests for ``agentforge init`` with flags."""

    # ── Acceptance scenario from TODO-v2-8 ────────────────────────────────────

    def test_acceptance_scenario(self, tmp_path):
        """agentforge init --withPlanner --agents alpha,beta --mcp foo --http bar
        must produce a valid project.yaml that loads without errors."""
        result = _invoke_init([
            "--withPlanner",
            "--agents", "alpha,beta",
            "--mcp", "foo",
            "--http", "bar",
            "--output", str(tmp_path),
        ])
        assert result.exit_code == 0, result.output
        yaml_path = tmp_path / "project.yaml"
        assert yaml_path.exists()
        config = load(yaml_path)
        assert config.pattern == "planner"
        assert len(config.agents) == 2
        agent_keys = {a.key for a in config.agents}
        assert agent_keys == {"alpha", "beta"}

    # ── Each pattern flag produces correct pattern ─────────────────────────────

    @pytest.mark.parametrize("flag,expected_pattern", [
        ("--withReactAgent", "react"),
        ("--withWorkflow", "workflow"),
        ("--withFanout", "fanout"),
        ("--withOrchestrator", "orchestrator"),
        ("--withPlanner", "planner"),
    ])
    def test_pattern_flag_sets_pattern(self, flag, expected_pattern, tmp_path):
        result = _invoke_init([
            flag,
            "--agents", "alpha",
            "--output", str(tmp_path),
        ])
        assert result.exit_code == 0, result.output
        config = load(tmp_path / "project.yaml")
        assert config.pattern == expected_pattern

    # ── Each entry flag produces correct entry type ────────────────────────────

    @pytest.mark.parametrize("flag,expected_type", [
        ("--withIntentRouter", "intent_router"),
        ("--withPassthrough", "passthrough"),
        ("--withDirectInput", "direct"),
    ])
    def test_entry_flag_sets_entry_type(self, flag, expected_type, tmp_path):
        result = _invoke_init([
            flag,
            "--agents", "alpha",
            "--output", str(tmp_path),
        ])
        assert result.exit_code == 0, result.output
        config = load(tmp_path / "project.yaml")
        assert config.entry is not None
        assert config.entry.type == expected_type

    # ── orchestratorKind ──────────────────────────────────────────────────────

    def test_orchestrator_kind_llm(self, tmp_path):
        result = _invoke_init([
            "--withOrchestrator",
            "--orchestratorKind", "llm",
            "--agents", "alpha",
            "--output", str(tmp_path),
        ])
        assert result.exit_code == 0, result.output
        config = load(tmp_path / "project.yaml")
        assert config.orchestrator is not None
        assert config.orchestrator.kind == "llm"

    def test_orchestrator_kind_rule(self, tmp_path):
        result = _invoke_init([
            "--withOrchestrator",
            "--orchestratorKind", "rule",
            "--agents", "alpha",
            "--output", str(tmp_path),
        ])
        assert result.exit_code == 0, result.output
        config = load(tmp_path / "project.yaml")
        assert config.orchestrator.kind == "rule"

    def test_invalid_orchestrator_kind_fails(self, tmp_path):
        result = _invoke_init([
            "--withOrchestrator",
            "--orchestratorKind", "invalid_xyz",
            "--agents", "alpha",
            "--output", str(tmp_path),
        ])
        assert result.exit_code != 0

    # ── Tool flags ────────────────────────────────────────────────────────────

    def test_mcp_tool_attached_to_agents(self, tmp_path):
        result = _invoke_init([
            "--withPlanner",
            "--agents", "alpha",
            "--mcp", "my_mcp",
            "--output", str(tmp_path),
        ])
        assert result.exit_code == 0, result.output
        config = load(tmp_path / "project.yaml")
        tool_names = {t.name for t in config.agents[0].tools}
        assert "my_mcp" in tool_names

    def test_multiple_mcp_flags(self, tmp_path):
        """--mcp may be specified multiple times; all names appear."""
        result = _invoke_init([
            "--withPlanner",
            "--agents", "alpha",
            "--mcp", "foo",
            "--mcp", "bar",
            "--output", str(tmp_path),
        ])
        assert result.exit_code == 0, result.output
        config = load(tmp_path / "project.yaml")
        tool_names = {t.name for t in config.agents[0].tools}
        assert "foo" in tool_names
        assert "bar" in tool_names

    def test_http_tool_attached(self, tmp_path):
        result = _invoke_init([
            "--withPlanner",
            "--agents", "alpha",
            "--http", "my_api",
            "--output", str(tmp_path),
        ])
        assert result.exit_code == 0, result.output
        config = load(tmp_path / "project.yaml")
        kinds = {t.kind for t in config.agents[0].tools}
        assert "http" in kinds

    def test_agent_tool_attached(self, tmp_path):
        result = _invoke_init([
            "--withPlanner",
            "--agents", "alpha",
            "--agent", "downstream",
            "--output", str(tmp_path),
        ])
        assert result.exit_code == 0, result.output
        config = load(tmp_path / "project.yaml")
        kinds = {t.kind for t in config.agents[0].tools}
        assert "agent" in kinds

    # ── --name flag ───────────────────────────────────────────────────────────

    def test_name_flag_sets_project_name(self, tmp_path):
        result = _invoke_init([
            "--withPlanner",
            "--agents", "alpha",
            "--name", "my_custom_project",
            "--output", str(tmp_path),
        ])
        assert result.exit_code == 0, result.output
        config = load(tmp_path / "project.yaml")
        assert config.metadata.name == "my_custom_project"

    def test_default_project_name_when_no_name_flag(self, tmp_path):
        result = _invoke_init([
            "--withPlanner",
            "--agents", "alpha",
            "--output", str(tmp_path),
        ])
        assert result.exit_code == 0, result.output
        config = load(tmp_path / "project.yaml")
        assert config.metadata.name == "my_agent_project"

    # ── Mutual exclusion: pattern flags ───────────────────────────────────────

    def test_mutual_exclusion_two_patterns_fails(self, tmp_path):
        """--withReactAgent --withPlanner must fail with a clear error."""
        result = _invoke_init([
            "--withReactAgent",
            "--withPlanner",
            "--agents", "alpha",
            "--output", str(tmp_path),
        ])
        assert result.exit_code != 0

    def test_mutual_exclusion_three_patterns_fails(self, tmp_path):
        result = _invoke_init([
            "--withReactAgent",
            "--withPlanner",
            "--withFanout",
            "--agents", "alpha",
            "--output", str(tmp_path),
        ])
        assert result.exit_code != 0

    # ── Mutual exclusion: entry flags ─────────────────────────────────────────

    def test_mutual_exclusion_two_entry_flags_fails(self, tmp_path):
        result = _invoke_init([
            "--withIntentRouter",
            "--withPassthrough",
            "--agents", "alpha",
            "--output", str(tmp_path),
        ])
        assert result.exit_code != 0

    # ── project.yaml already exists without --force ───────────────────────────

    def test_existing_yaml_without_force_fails(self, tmp_path):
        (tmp_path / "project.yaml").write_text("metadata:\n  name: existing\n")
        result = _invoke_init([
            "--withPlanner",
            "--agents", "alpha",
            "--output", str(tmp_path),
        ])
        assert result.exit_code != 0

    def test_existing_yaml_with_force_succeeds(self, tmp_path):
        (tmp_path / "project.yaml").write_text("metadata:\n  name: existing\n")
        result = _invoke_init([
            "--withPlanner",
            "--agents", "alpha",
            "--output", str(tmp_path),
            "--force",
        ])
        assert result.exit_code == 0, result.output

    # ── Round-trip property ────────────────────────────────────────────────────

    @pytest.mark.parametrize("pattern,agents", [
        ("react", "alpha"),
        ("fanout", "alpha,beta"),
        ("orchestrator", "sql"),
        ("planner", "alpha,beta"),
    ])
    def test_round_trip_dump_load(self, pattern, agents, tmp_path):
        """Every valid flag combination must round-trip through dump/load unchanged."""
        flag = f"--with{pattern.capitalize()}"
        if pattern == "react":
            flag = "--withReactAgent"
        result = _invoke_init([
            flag,
            "--agents", agents,
            "--output", str(tmp_path),
        ])
        assert result.exit_code == 0, result.output

        # Load once from disk.
        yaml_path = tmp_path / "project.yaml"
        config1 = load(yaml_path)

        # Re-dump and re-load.
        import yaml as _yaml
        from agentforge.schema.loader import dump
        dump(config1, yaml_path)
        config2 = load(yaml_path)

        assert config1.model_dump(mode="json", exclude_none=True) == \
               config2.model_dump(mode="json", exclude_none=True)

    def test_round_trip_workflow_pattern(self, tmp_path):
        """workflow pattern needs special handling (auto step injection)."""
        result = _invoke_init([
            "--withWorkflow",
            "--agents", "alpha",
            "--output", str(tmp_path),
        ])
        assert result.exit_code == 0, result.output
        yaml_path = tmp_path / "project.yaml"
        config1 = load(yaml_path)
        assert config1.pattern == "workflow"
        assert config1.workflow_sm is not None
        assert len(config1.workflow_sm.steps) >= 1

        from agentforge.schema.loader import dump
        dump(config1, yaml_path)
        config2 = load(yaml_path)
        assert config1.model_dump(mode="json", exclude_none=True) == \
               config2.model_dump(mode="json", exclude_none=True)

    # ── Valid YAML produced ────────────────────────────────────────────────────

    def test_output_is_valid_yaml(self, tmp_path):
        _invoke_init([
            "--withPlanner",
            "--agents", "alpha",
            "--output", str(tmp_path),
        ])
        raw = (tmp_path / "project.yaml").read_text()
        parsed = yaml.safe_load(raw)
        assert isinstance(parsed, dict)

    def test_combined_entry_and_pattern(self, tmp_path):
        result = _invoke_init([
            "--withPassthrough",
            "--withFanout",
            "--agents", "alpha,beta",
            "--output", str(tmp_path),
        ])
        assert result.exit_code == 0, result.output
        config = load(tmp_path / "project.yaml")
        assert config.entry.type == "passthrough"
        assert config.pattern == "fanout"

    # ── Tool-heavy round-trip ─────────────────────────────────────────────────

    def test_tool_heavy_round_trip(self, tmp_path):
        """All three tool kinds + multiple agents + --withOrchestrator --orchestratorKind rule
        must produce a valid YAML that round-trips through dump/load unchanged."""
        result = _invoke_init([
            "--withOrchestrator",
            "--orchestratorKind", "rule",
            "--agents", "alpha,beta",
            "--mcp", "my_mcp",
            "--http", "my_http",
            "--agent", "downstream",
            "--output", str(tmp_path),
        ])
        assert result.exit_code == 0, result.output

        yaml_path = tmp_path / "project.yaml"
        config1 = load(yaml_path)

        # Verify all tool kinds present on each agent.
        for agent in config1.agents:
            kinds = {t.kind for t in agent.tools}
            assert kinds == {"mcp", "http", "agent"}, f"Agent {agent.key} missing tool kinds: {kinds}"

        # Verify orchestrator kind preserved.
        assert config1.orchestrator is not None
        assert config1.orchestrator.kind == "rule"

        # Round-trip: dump then reload must be identical.
        from agentforge.schema.loader import dump
        dump(config1, yaml_path)
        config2 = load(yaml_path)
        assert config1.model_dump(mode="json", exclude_none=True) ==                config2.model_dump(mode="json", exclude_none=True)

    # ── orchestratorKind without --withOrchestrator ───────────────────────────

    def test_orchestrator_kind_without_with_orchestrator(self, tmp_path):
        """--orchestratorKind rule without --withOrchestrator: command should succeed
        (v2_flags_given=True due to orchestrator_kind), config loads without error.
        The pattern falls back to 'orchestrator' via legacy-compat validator."""
        result = _invoke_init([
            "--orchestratorKind", "rule",
            "--agents", "alpha",
            "--output", str(tmp_path),
        ])
        # Behavior is: succeeds (exit 0), config is valid.
        assert result.exit_code == 0, result.output
        config = load(tmp_path / "project.yaml")
        # Legacy compat fires: pattern defaults to orchestrator.
        assert config.pattern == "orchestrator"

    # ── Duplicate agent keys ──────────────────────────────────────────────────

    def test_duplicate_agent_keys_rejected_by_schema(self, tmp_path):
        """Schema rejects duplicate agent keys with a ValidationError.
        --agents alpha,alpha must fail at config validation (exit code != 0)."""
        result = _invoke_init([
            "--withPlanner",
            "--agents", "alpha,alpha",
            "--output", str(tmp_path),
        ])
        # Validator raises ValueError -> CLI catches and exits with code 2.
        assert result.exit_code != 0

