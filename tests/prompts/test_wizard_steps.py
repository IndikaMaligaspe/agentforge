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
    step_development,
    step_ci,
    step_testing,
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

    def _fake_ask_workflow(agent_keys, db_backend="postgres"):
        captured["agent_keys"] = agent_keys
        return {
            "enable_feedback_loop": True,
            "enable_validation_node": True,
            "default_intent": agent_keys[0],
            "max_feedback_attempts": 3,
            "enable_checkpointing": False,
        }

    monkeypatch.setattr(f"{_WIZARD}.ask_workflow_config", _fake_ask_workflow)

    partial = {"agents": [_make_agent("sql"), _make_agent("analytics")]}
    result = step_workflow(partial)

    assert captured["agent_keys"] == ["sql", "analytics"]
    assert result["workflow"]["default_intent"] == "sql"


def test_step_workflow_empty_agents_list(monkeypatch):
    """step_workflow with no agents in partial passes an empty list."""
    monkeypatch.setattr(
        f"{_WIZARD}.ask_workflow_config",
        lambda agent_keys, db_backend="postgres": {
            "enable_feedback_loop": False,
            "enable_validation_node": False,
            "default_intent": "sql",
            "max_feedback_attempts": 1,
            "enable_checkpointing": False,
        },
    )

    result = step_workflow({})
    assert "workflow" in result


def test_step_workflow_postgres_asks_checkpointing(monkeypatch):
    """When database backend is postgres, ask_workflow_config receives db_backend='postgres'."""
    captured = {}

    def _fake_ask_workflow(agent_keys, db_backend="postgres"):
        captured["db_backend"] = db_backend
        return {
            "enable_feedback_loop": True,
            "enable_validation_node": True,
            "default_intent": "sql",
            "max_feedback_attempts": 3,
            "enable_checkpointing": True,
        }

    monkeypatch.setattr(f"{_WIZARD}.ask_workflow_config", _fake_ask_workflow)

    partial = {
        "agents": [_make_agent("sql")],
        "database": {"backend": "postgres"},
    }
    result = step_workflow(partial)

    assert captured["db_backend"] == "postgres"
    assert result["workflow"]["enable_checkpointing"] is True


def test_step_workflow_sqlite_skips_checkpointing(monkeypatch):
    """When database backend is sqlite, ask_workflow_config receives db_backend='sqlite'."""
    captured = {}

    def _fake_ask_workflow(agent_keys, db_backend="postgres"):
        captured["db_backend"] = db_backend
        # Simulate what the real ask_workflow_config does for non-postgres: set False.
        return {
            "enable_feedback_loop": True,
            "enable_validation_node": True,
            "default_intent": "sql",
            "max_feedback_attempts": 3,
            "enable_checkpointing": False,
        }

    monkeypatch.setattr(f"{_WIZARD}.ask_workflow_config", _fake_ask_workflow)

    partial = {
        "agents": [_make_agent("sql")],
        "database": {"backend": "sqlite"},
    }
    result = step_workflow(partial)

    assert captured["db_backend"] == "sqlite"
    assert result["workflow"]["enable_checkpointing"] is False


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


def test_step_security_returns_auth_type_none(monkeypatch):
    """step_security with auth_type='none' must produce security.auth_type='none'."""
    monkeypatch.setattr(f"{_WIZARD}.ask_security_config", lambda: {
        "auth_type": "none",
        "api_key_env_var": "API_KEY",
        "jwt_algorithm": None,
        "jwt_issuer": None,
        "jwt_audience": None,
        "jwks_url": None,
        "enable_ip_pseudonymization": False,
    })

    result = step_security({})
    assert result["security"]["auth_type"] == "none"


def test_step_security_returns_auth_type_api_key(monkeypatch):
    """step_security with auth_type='api_key' must produce security.auth_type='api_key'."""
    monkeypatch.setattr(f"{_WIZARD}.ask_security_config", lambda: {
        "auth_type": "api_key",
        "api_key_env_var": "MY_KEY",
        "jwt_algorithm": None,
        "jwt_issuer": None,
        "jwt_audience": None,
        "jwks_url": None,
        "enable_ip_pseudonymization": False,
    })

    result = step_security({})
    assert result["security"]["auth_type"] == "api_key"
    assert result["security"]["api_key_env_var"] == "MY_KEY"


def test_step_security_returns_auth_type_jwt_hs256(monkeypatch):
    """step_security with auth_type='jwt'/HS256 must include jwt_algorithm."""
    monkeypatch.setattr(f"{_WIZARD}.ask_security_config", lambda: {
        "auth_type": "jwt",
        "api_key_env_var": "API_KEY",
        "jwt_algorithm": "HS256",
        "jwt_issuer": None,
        "jwt_audience": None,
        "jwks_url": None,
        "enable_ip_pseudonymization": False,
    })

    result = step_security({})
    assert result["security"]["auth_type"] == "jwt"
    assert result["security"]["jwt_algorithm"] == "HS256"
    assert result["security"]["jwks_url"] is None


def test_step_security_jwt_rs256_collects_jwks_url(monkeypatch):
    """JWT path with RS256 must collect jwks_url."""
    monkeypatch.setattr(f"{_WIZARD}.ask_security_config", lambda: {
        "auth_type": "jwt",
        "api_key_env_var": "API_KEY",
        "jwt_algorithm": "RS256",
        "jwt_issuer": None,
        "jwt_audience": None,
        "jwks_url": "https://example.com/.well-known/jwks.json",
        "enable_ip_pseudonymization": False,
    })

    result = step_security({})
    assert result["security"]["auth_type"] == "jwt"
    assert result["security"]["jwt_algorithm"] == "RS256"
    assert result["security"]["jwks_url"] == "https://example.com/.well-known/jwks.json"


def test_step_security_jwt_hs256_no_jwks_url(monkeypatch):
    """JWT path with HS256 must NOT prompt for jwks_url (returns None)."""
    monkeypatch.setattr(f"{_WIZARD}.ask_security_config", lambda: {
        "auth_type": "jwt",
        "api_key_env_var": "API_KEY",
        "jwt_algorithm": "HS256",
        "jwt_issuer": None,
        "jwt_audience": None,
        "jwks_url": None,
        "enable_ip_pseudonymization": False,
    })

    result = step_security({})
    assert result["security"]["jwt_algorithm"] == "HS256"
    assert result["security"]["jwks_url"] is None


def test_build_config_with_jwt_hs256():
    """build_config must produce a valid ProjectConfig for JWT/HS256."""
    partial = {
        "metadata": {
            "name": "jwt_proj",
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
            "title": "JWT API",
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
            "auth_type": "jwt",
            "api_key_env_var": "API_KEY",
            "jwt_algorithm": "HS256",
            "jwt_issuer": None,
            "jwt_audience": None,
            "jwks_url": None,
            "enable_ip_pseudonymization": False,
        },
    }

    config = build_config(partial)

    assert isinstance(config, ProjectConfig)
    assert config.security.auth_type == "jwt"
    assert config.security.jwt_algorithm == "HS256"
    assert config.security.enable_auth is True


def test_build_config_with_jwt_rs256():
    """build_config must produce a valid ProjectConfig for JWT/RS256 with jwks_url."""
    partial = {
        "metadata": {
            "name": "jwt_rs256_proj",
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
            "title": "JWT RS256 API",
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
            "auth_type": "jwt",
            "api_key_env_var": "API_KEY",
            "jwt_algorithm": "RS256",
            "jwt_issuer": "https://auth.example.com/",
            "jwt_audience": "my-api",
            "jwks_url": "https://example.com/.well-known/jwks.json",
            "enable_ip_pseudonymization": False,
        },
    }

    config = build_config(partial)

    assert isinstance(config, ProjectConfig)
    assert config.security.auth_type == "jwt"
    assert config.security.jwt_algorithm == "RS256"
    assert config.security.jwks_url == "https://example.com/.well-known/jwks.json"
    assert config.security.jwt_issuer == "https://auth.example.com/"
    assert config.security.jwt_audience == "my-api"
    assert config.security.enable_auth is True


# ── step_development ──────────────────────────────────────────────────────────

def test_step_development_merges_development_key(monkeypatch):
    """step_development must add 'development' key and leave other keys untouched."""
    monkeypatch.setattr(f"{_WIZARD}.ask_development_config", lambda: {
        "pre_commit": True,
    })

    result = step_development({"existing": "value"})
    assert result["existing"] == "value"
    assert result["development"]["pre_commit"] is True


def test_step_development_pre_commit_false(monkeypatch):
    """step_development with pre_commit=False must set development.pre_commit=False."""
    monkeypatch.setattr(f"{_WIZARD}.ask_development_config", lambda: {
        "pre_commit": False,
    })

    result = step_development({})
    assert result["development"]["pre_commit"] is False


def test_step_development_does_not_mutate_input(monkeypatch):
    """step_development must not mutate the incoming partial dict."""
    monkeypatch.setattr(f"{_WIZARD}.ask_development_config", lambda: {
        "pre_commit": True,
    })

    initial = {"metadata": {"name": "x"}}
    step_development(initial)
    assert "development" not in initial


# ── step_ci ───────────────────────────────────────────────────────────────────

def test_step_ci_merges_ci_key(monkeypatch):
    """step_ci must add 'ci' key and leave other keys untouched."""
    monkeypatch.setattr(f"{_WIZARD}.ask_ci_config", lambda: {
        "provider": "github",
        "python_version": "3.12",
        "installer": "uv",
    })

    result = step_ci({"existing": "value"})
    assert result["existing"] == "value"
    assert result["ci"]["provider"] == "github"
    assert result["ci"]["python_version"] == "3.12"
    assert result["ci"]["installer"] == "uv"


def test_step_ci_does_not_mutate_input(monkeypatch):
    """step_ci must not mutate the incoming partial dict."""
    monkeypatch.setattr(f"{_WIZARD}.ask_ci_config", lambda: {
        "provider": "none",
        "python_version": "3.12",
        "installer": "uv",
    })

    initial = {"metadata": {"name": "x"}}
    step_ci(initial)
    assert "ci" not in initial


def test_step_ci_provider_none_default(monkeypatch):
    """step_ci with provider=none must produce ci.provider == 'none'."""
    monkeypatch.setattr(f"{_WIZARD}.ask_ci_config", lambda: {
        "provider": "none",
        "python_version": "3.12",
        "installer": "uv",
    })

    result = step_ci({})
    assert result["ci"]["provider"] == "none"


def test_step_ci_pip_installer(monkeypatch):
    """step_ci must accept installer=pip."""
    monkeypatch.setattr(f"{_WIZARD}.ask_ci_config", lambda: {
        "provider": "github",
        "python_version": "3.11",
        "installer": "pip",
    })

    result = step_ci({})
    assert result["ci"]["installer"] == "pip"


def test_step_ci_poetry_installer(monkeypatch):
    """step_ci must accept installer=poetry."""
    monkeypatch.setattr(f"{_WIZARD}.ask_ci_config", lambda: {
        "provider": "github",
        "python_version": "3.13",
        "installer": "poetry",
    })

    result = step_ci({})
    assert result["ci"]["installer"] == "poetry"
    assert result["ci"]["python_version"] == "3.13"


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


def test_build_config_with_ci_github():
    """build_config must produce a valid ProjectConfig with ci.provider=github."""
    partial = {
        "metadata": {
            "name": "ci_proj",
            "description": "desc",
            "python_version": "3.12",
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
            "title": "CI API",
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
        "ci": {
            "provider": "github",
            "python_version": "3.12",
            "installer": "poetry",
        },
    }

    config = build_config(partial)

    assert isinstance(config, ProjectConfig)
    assert config.ci.provider == "github"
    assert config.ci.installer == "poetry"
    assert config.ci.python_version == "3.12"


# ── Baseline end-to-end: all defaults produce a valid ProjectConfig ────────────

def test_wizard_all_defaults_produces_valid_config(monkeypatch):
    """
    Baseline test: composing all steps with their default responses must produce
    a valid ProjectConfig without raising a Pydantic ValidationError.
    This simulates a user pressing Enter through every prompt.
    development defaults to pre_commit=False so no pre-commit file is generated.
    ci defaults to provider=none so the CI file is NOT generated.
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

    monkeypatch.setattr(
        f"{_WIZARD}.ask_workflow_config",
        lambda agent_keys, db_backend="postgres": {
            "enable_feedback_loop": True,
            "enable_validation_node": True,
            "default_intent": agent_keys[0] if agent_keys else "sql",
            "max_feedback_attempts": 3,
            "enable_checkpointing": False,
        },
    )

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

    monkeypatch.setattr(f"{_WIZARD}.ask_development_config", lambda: {
        "pre_commit": False,
    })

    monkeypatch.setattr(f"{_WIZARD}.ask_ci_config", lambda: {
        "provider": "none",
        "python_version": "3.12",
        "installer": "uv",
    })

    monkeypatch.setattr(f"{_WIZARD}.ask_testing_config", lambda: {
        "eval_framework": "none",
        "enable_benchmarks": False,
    })

    partial: dict = {}
    partial = step_metadata(partial)
    partial = step_agents(partial)
    partial = step_database(partial)
    partial = step_workflow(partial)
    partial = step_api(partial)
    partial = step_observability(partial)
    partial = step_security(partial)
    partial = step_development(partial)
    partial = step_ci(partial)
    partial = step_testing(partial)

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
    # Development defaults to pre_commit=False — the opt-in is off
    assert config.development.pre_commit is False
    # CI defaults to none — the opt-in is off
    assert config.ci.provider == "none"
    # Testing defaults to none — the opt-in is off
    assert config.testing.eval_framework == "none"
    assert config.testing.enable_benchmarks is False


# ── Extended database step (TODO-1): backend + use_alembic ────────────────────

def test_step_database_includes_use_alembic_true(monkeypatch):
    """step_database must pass use_alembic=True when ask_database_config returns it."""
    monkeypatch.setattr(f"{_WIZARD}.ask_database_config", lambda: {
        "backend": "mysql",
        "tables": [],
        "connection_env_var": "DATABASE_URL",
        "pool_size": 5,
        "max_overflow": 10,
        "use_alembic": True,
    })

    result = step_database({})
    assert result["database"]["backend"] == "mysql"
    assert result["database"]["use_alembic"] is True


def test_step_database_includes_use_alembic_false(monkeypatch):
    """step_database must pass use_alembic=False (default) when not requested."""
    monkeypatch.setattr(f"{_WIZARD}.ask_database_config", lambda: {
        "backend": "sqlite",
        "tables": [],
        "connection_env_var": "DATABASE_URL",
        "pool_size": 1,
        "max_overflow": 0,
        "use_alembic": False,
    })

    result = step_database({})
    assert result["database"]["backend"] == "sqlite"
    assert result["database"]["use_alembic"] is False


def test_build_config_with_mysql_and_alembic():
    """build_config must construct a valid ProjectConfig for mysql + use_alembic=True."""
    partial = {
        "metadata": {
            "name": "mysql_proj",
            "description": "desc",
            "python_version": "3.11",
            "author": "A",
            "email": "a@b.com",
        },
        "agents": [_make_agent("sql", "SqlAgent")],
        "database": {
            "backend": "mysql",
            "tables": [],
            "connection_env_var": "DATABASE_URL",
            "pool_size": 5,
            "max_overflow": 10,
            "use_alembic": True,
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
        "development": {
            "pre_commit": False,
        },
    }

    config = build_config(partial)

    assert isinstance(config, ProjectConfig)
    assert config.database.backend.value == "mysql"
    assert config.database.use_alembic is True


def test_step_database_sqlite_no_use_alembic_does_not_error(monkeypatch):
    """sqlite + use_alembic=False must still produce a valid partial dict."""
    monkeypatch.setattr(f"{_WIZARD}.ask_database_config", lambda: {
        "backend": "sqlite",
        "tables": [],
        "connection_env_var": "DATABASE_URL",
        "pool_size": 1,
        "max_overflow": 0,
        "use_alembic": False,
    })

    result = step_database({"existing": "value"})
    assert result["existing"] == "value"
    assert result["database"]["backend"] == "sqlite"
    assert result["database"]["use_alembic"] is False


# ── Fix 4: wizard defensive reset ────────────────────────────────────────────

def test_step_workflow_forces_checkpointing_off_for_non_postgres(monkeypatch):
    """step_workflow must set enable_checkpointing=False when backend is not postgres.

    Even if ask_workflow_config returns enable_checkpointing=True (a stale value
    from a previous postgres run), step_workflow must override it to False for
    sqlite and any other non-postgres backend.
    """
    monkeypatch.setattr(
        f"{_WIZARD}.ask_workflow_config",
        lambda agent_keys, db_backend="postgres": {
            "enable_feedback_loop": False,
            "enable_validation_node": False,
            "default_intent": "sql",
            "max_feedback_attempts": 1,
            # Simulate stale True from a prior postgres run
            "enable_checkpointing": True,
        },
    )

    partial = {
        "agents": [_make_agent("sql")],
        "database": {"backend": "sqlite"},
    }
    result = step_workflow(partial)

    assert result["workflow"]["enable_checkpointing"] is False


# ── step_testing (TODO-7) ─────────────────────────────────────────────────────

def test_step_testing_merges_testing_key(monkeypatch):
    """step_testing must add 'testing' key and leave other keys untouched."""
    monkeypatch.setattr(f"{_WIZARD}.ask_testing_config", lambda: {
        "eval_framework": "none",
        "enable_benchmarks": False,
    })

    result = step_testing({"existing": "value"})
    assert result["existing"] == "value"
    assert result["testing"]["eval_framework"] == "none"
    assert result["testing"]["enable_benchmarks"] is False


def test_step_testing_does_not_mutate_input(monkeypatch):
    """step_testing must not mutate the incoming partial dict."""
    monkeypatch.setattr(f"{_WIZARD}.ask_testing_config", lambda: {
        "eval_framework": "none",
        "enable_benchmarks": False,
    })

    initial = {"metadata": {"name": "x"}}
    step_testing(initial)
    assert "testing" not in initial


def test_step_testing_deepeval_framework(monkeypatch):
    """step_testing with eval_framework=deepeval must set testing.eval_framework='deepeval'."""
    monkeypatch.setattr(f"{_WIZARD}.ask_testing_config", lambda: {
        "eval_framework": "deepeval",
        "enable_benchmarks": False,
    })

    result = step_testing({})
    assert result["testing"]["eval_framework"] == "deepeval"
    assert result["testing"]["enable_benchmarks"] is False


def test_step_testing_deepeval_with_benchmarks(monkeypatch):
    """step_testing with deepeval + enable_benchmarks=True produces correct testing dict."""
    monkeypatch.setattr(f"{_WIZARD}.ask_testing_config", lambda: {
        "eval_framework": "deepeval",
        "enable_benchmarks": True,
    })

    result = step_testing({})
    assert result["testing"]["eval_framework"] == "deepeval"
    assert result["testing"]["enable_benchmarks"] is True


def test_step_testing_none_framework_preserves_false_benchmarks(monkeypatch):
    """step_testing with eval_framework=none must always set enable_benchmarks=False."""
    monkeypatch.setattr(f"{_WIZARD}.ask_testing_config", lambda: {
        "eval_framework": "none",
        "enable_benchmarks": False,
    })

    result = step_testing({"other": 42})
    assert result["other"] == 42
    assert result["testing"]["eval_framework"] == "none"
    assert result["testing"]["enable_benchmarks"] is False


def test_build_config_with_deepeval_benchmarks():
    """build_config must construct a valid ProjectConfig with deepeval benchmarks enabled."""
    partial = {
        "metadata": {
            "name": "bench_proj",
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
            "title": "Bench API",
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
        "testing": {
            "eval_framework": "deepeval",
            "enable_benchmarks": True,
        },
    }

    config = build_config(partial)

    assert isinstance(config, ProjectConfig)
    assert config.testing.eval_framework == "deepeval"
    assert config.testing.enable_benchmarks is True


def test_build_config_testing_defaults_when_absent():
    """build_config with no 'testing' key in partial must default to eval_framework=none."""
    partial = {
        "metadata": {
            "name": "no_testing_proj",
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
    assert config.testing.eval_framework == "none"
    assert config.testing.enable_benchmarks is False
