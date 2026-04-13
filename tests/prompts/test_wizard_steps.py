"""
Unit tests for the composable wizard step functions.

Each step is tested in isolation by monkeypatching the question helpers and
questionary directly at the location where wizard.py resolves them. Tests
verify the pure dict-in / dict-out contract: a step takes a partial dict,
adds its keys, and returns the updated dict without mutating the original.
"""
import pytest

from agentforge.prompts.wizard import (
    step_metadata,
    step_agents,
    step_database,
    step_workflow,
    step_api,
    step_observability,
    step_security,
    build_config,
)
from agentforge.schema.models import (
    AgentConfig, LLMModel, ProjectConfig,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_question_mock(return_value):
    """Return a mock that mimics questionary's fluent .ask() pattern."""
    class _MockQuestion:
        def ask(self):
            return return_value
    return _MockQuestion()


def _make_agent(key="sql", class_name="SqlAgent"):
    return AgentConfig(
        key=key,
        class_name=class_name,
        llm_model=LLMModel.GPT4O_MINI,
        system_prompt="You are a helpful assistant.",
        needs_validation=False,
    )


# Patch target: the names as bound in agentforge.prompts.wizard
_WIZARD = "agentforge.prompts.wizard"


# ── step_metadata ─────────────────────────────────────────────────────────────

def test_step_metadata_merges_into_partial(monkeypatch):
    """step_metadata must add 'metadata' key and leave other keys untouched."""
    monkeypatch.setattr(f"{_WIZARD}.ask_project_metadata", lambda: {
        "name": "my_project",
        "description": "A test project",
        "python_version": "3.11",
        "author": "Test Author",
        "email": "test@example.com",
    })

    initial = {"existing_key": "preserved"}
    result = step_metadata(initial)

    assert result["existing_key"] == "preserved"
    assert result["metadata"]["name"] == "my_project"
    assert result["metadata"]["python_version"] == "3.11"


def test_step_metadata_does_not_mutate_input(monkeypatch):
    """step_metadata must not mutate the incoming partial dict."""
    monkeypatch.setattr(f"{_WIZARD}.ask_project_metadata", lambda: {
        "name": "my_project",
        "description": "desc",
        "python_version": "3.12",
        "author": "A",
        "email": "a@b.com",
    })

    initial = {}
    step_metadata(initial)
    assert initial == {}


# ── step_agents ───────────────────────────────────────────────────────────────

def test_step_agents_adds_single_agent(monkeypatch):
    """step_agents with num_agents=1 produces a list with one AgentConfig."""
    import questionary as q

    monkeypatch.setattr(q, "text", lambda *a, **kw: _make_question_mock("1"))
    monkeypatch.setattr(f"{_WIZARD}.ask_agent_config", lambda existing_keys: _make_agent("sql", "SqlAgent"))

    result = step_agents({})
    assert "agents" in result
    assert len(result["agents"]) == 1
    assert result["agents"][0].key == "sql"


def test_step_agents_multiple_agents(monkeypatch):
    """step_agents with num_agents=2 calls ask_agent_config twice."""
    import questionary as q

    call_count = {"n": 0}
    keys = ["sql", "analytics"]

    monkeypatch.setattr(q, "text", lambda *a, **kw: _make_question_mock("2"))

    def _side_effect(existing_keys):
        k = keys[call_count["n"]]
        call_count["n"] += 1
        return _make_agent(k, k.capitalize() + "Agent")

    monkeypatch.setattr(f"{_WIZARD}.ask_agent_config", _side_effect)

    result = step_agents({})
    assert len(result["agents"]) == 2
    assert {a.key for a in result["agents"]} == {"sql", "analytics"}


def test_step_agents_does_not_mutate_input(monkeypatch):
    import questionary as q

    monkeypatch.setattr(q, "text", lambda *a, **kw: _make_question_mock("1"))
    monkeypatch.setattr(f"{_WIZARD}.ask_agent_config", lambda existing_keys: _make_agent())

    initial = {"metadata": {"name": "x"}}
    step_agents(initial)
    assert "agents" not in initial


# ── step_database ─────────────────────────────────────────────────────────────

def test_step_database_merges_database_key(monkeypatch):
    monkeypatch.setattr(f"{_WIZARD}.ask_database_config", lambda: {
        "backend": "postgres",
        "tables": [],
        "connection_env_var": "DATABASE_URL",
        "pool_size": 5,
        "max_overflow": 10,
    })

    result = step_database({"x": 1})
    assert result["x"] == 1
    assert result["database"]["backend"] == "postgres"
    assert result["database"]["pool_size"] == 5


def test_step_database_does_not_mutate_input(monkeypatch):
    monkeypatch.setattr(f"{_WIZARD}.ask_database_config", lambda: {
        "backend": "sqlite",
        "tables": [],
        "connection_env_var": "DATABASE_URL",
        "pool_size": 1,
        "max_overflow": 0,
    })

    initial = {}
    step_database(initial)
    assert initial == {}


# ── step_workflow ─────────────────────────────────────────────────────────────

def test_step_workflow_uses_agents_from_partial(monkeypatch):
    """step_workflow must read agent keys from partial dict and pass them through."""
    captured = {}

    def _fake_ask_workflow(agent_keys):
        captured["agent_keys"] = agent_keys
        return {
            "enable_feedback_loop": True,
            "enable_validation_node": True,
            "default_intent": agent_keys[0],
            "max_feedback_attempts": 3,
        }

    monkeypatch.setattr(f"{_WIZARD}.ask_workflow_config", _fake_ask_workflow)

    partial = {"agents": [_make_agent("sql"), _make_agent("analytics")]}
    result = step_workflow(partial)

    assert captured["agent_keys"] == ["sql", "analytics"]
    assert result["workflow"]["default_intent"] == "sql"


def test_step_workflow_empty_agents_list(monkeypatch):
    """step_workflow with no agents in partial passes an empty list."""
    monkeypatch.setattr(f"{_WIZARD}.ask_workflow_config", lambda agent_keys: {
        "enable_feedback_loop": False,
        "enable_validation_node": False,
        "default_intent": "sql",
        "max_feedback_attempts": 1,
    })

    result = step_workflow({})
    assert "workflow" in result


# ── step_api ──────────────────────────────────────────────────────────────────

def test_step_api_merges_api_key(monkeypatch):
    monkeypatch.setattr(f"{_WIZARD}.ask_api_config", lambda: {
        "title": "My API",
        "query_max_length": 2000,
        "cors": {"origins": ["*"], "allow_credentials": False},
    })

    result = step_api({})
    assert result["api"]["title"] == "My API"


# ── step_observability ────────────────────────────────────────────────────────

def test_step_observability_merges_observability_key(monkeypatch):
    monkeypatch.setattr(f"{_WIZARD}.ask_observability_config", lambda: {
        "enable_tracing": False,
        "tracing_provider": "langfuse",
        "context_fields": ["request_id"],
        "log_rotation_bytes": 10_485_760,
        "log_backup_count": 5,
    })

    result = step_observability({"x": 99})
    assert result["x"] == 99
    assert result["observability"]["enable_tracing"] is False


# ── step_security ─────────────────────────────────────────────────────────────

def test_step_security_merges_security_key(monkeypatch):
    monkeypatch.setattr(f"{_WIZARD}.ask_security_config", lambda: {
        "enable_auth": False,
        "api_key_env_var": "API_KEY",
        "enable_ip_pseudonymization": False,
    })

    result = step_security({})
    assert result["security"]["enable_auth"] is False


# ── build_config ──────────────────────────────────────────────────────────────

def test_build_config_produces_project_config():
    """build_config must construct a valid ProjectConfig from a complete partial dict."""
    partial = {
        "metadata": {
            "name": "test_proj",
            "description": "desc",
            "python_version": "3.11",
            "author": "A",
            "email": "a@b.com",
        },
        "agents": [_make_agent("sql", "SqlAgent")],
        "database": {
            "backend": "postgres",
            "tables": [],
            "connection_env_var": "DATABASE_URL",
            "pool_size": 5,
            "max_overflow": 10,
        },
        "workflow": {
            "enable_feedback_loop": True,
            "enable_validation_node": True,
            "default_intent": "sql",
            "max_feedback_attempts": 3,
        },
        "api": {
            "title": "Test API",
            "query_max_length": 2000,
            "cors": {"origins": ["*"], "allow_credentials": False},
        },
        "observability": {
            "enable_tracing": False,
            "tracing_provider": "langfuse",
            "context_fields": ["request_id"],
            "log_rotation_bytes": 10_485_760,
            "log_backup_count": 5,
        },
        "security": {
            "enable_auth": False,
            "api_key_env_var": "API_KEY",
            "enable_ip_pseudonymization": False,
        },
    }

    config = build_config(partial)

    assert isinstance(config, ProjectConfig)
    assert config.metadata.name == "test_proj"
    assert config.agents[0].key == "sql"
    assert config.workflow.default_intent == "sql"


# ── Baseline end-to-end: all defaults produce a valid ProjectConfig ────────────

def test_wizard_all_defaults_produces_valid_config(monkeypatch):
    """
    Baseline test: composing all steps with their default responses must produce
    a valid ProjectConfig without raising a Pydantic ValidationError.
    This simulates a user pressing Enter through every prompt.
    """
    import questionary as q

    monkeypatch.setattr(f"{_WIZARD}.ask_project_metadata", lambda: {
        "name": "my_project",
        "description": "An agentic project scaffolded by agentforge",
        "python_version": "3.11",
        "author": "Your Name",
        "email": "you@example.com",
    })

    # step_agents: num_agents text prompt returns "1"
    monkeypatch.setattr(q, "text", lambda *a, **kw: _make_question_mock("1"))
    monkeypatch.setattr(f"{_WIZARD}.ask_agent_config", lambda existing_keys: _make_agent("sql", "SqlAgent"))

    monkeypatch.setattr(f"{_WIZARD}.ask_database_config", lambda: {
        "backend": "postgres",
        "tables": [],
        "connection_env_var": "DATABASE_URL",
        "pool_size": 5,
        "max_overflow": 10,
    })

    monkeypatch.setattr(f"{_WIZARD}.ask_workflow_config", lambda agent_keys: {
        "enable_feedback_loop": True,
        "enable_validation_node": True,
        "default_intent": agent_keys[0] if agent_keys else "sql",
        "max_feedback_attempts": 3,
    })

    monkeypatch.setattr(f"{_WIZARD}.ask_api_config", lambda: {
        "title": "My Agentic API",
        "query_max_length": 2000,
        "cors": {"origins": ["*"], "allow_credentials": False},
    })

    monkeypatch.setattr(f"{_WIZARD}.ask_observability_config", lambda: {
        "enable_tracing": False,
        "tracing_provider": "langfuse",
        "context_fields": ["request_id", "user_id", "session_id"],
        "log_rotation_bytes": 10_485_760,
        "log_backup_count": 5,
    })

    monkeypatch.setattr(f"{_WIZARD}.ask_security_config", lambda: {
        "enable_auth": False,
        "api_key_env_var": "API_KEY",
        "enable_ip_pseudonymization": False,
    })

    partial: dict = {}
    partial = step_metadata(partial)
    partial = step_agents(partial)
    partial = step_database(partial)
    partial = step_workflow(partial)
    partial = step_api(partial)
    partial = step_observability(partial)
    partial = step_security(partial)

    config = build_config(partial)

    assert isinstance(config, ProjectConfig)
    assert config.metadata.name == "my_project"
    assert len(config.agents) == 1
    assert config.agents[0].key == "sql"
    assert config.workflow.default_intent == "sql"
    assert config.database.backend.value == "postgres"
    assert config.api.title == "My Agentic API"
    assert config.observability.enable_tracing is False
    assert config.security.enable_auth is False
