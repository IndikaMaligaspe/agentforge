"""
Tests for the WorkflowConfig.enable_checkpointing cross-field validator (TODO-9).

Covers the check_checkpointing_requires_postgres model_validator on ProjectConfig:
- enable_checkpointing=True with sqlite backend raises ValidationError.
- enable_checkpointing=True with mysql backend raises ValidationError.
- enable_checkpointing=True with postgres backend is valid.
- enable_checkpointing=False with sqlite backend is valid (default path).
"""
import pytest
from pydantic import ValidationError

from agentforge.schema.models import (
    AgentConfig,
    DatabaseConfig,
    DBBackend,
    LLMModel,
    ProjectConfig,
    ProjectMetadata,
    WorkflowConfig,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_config(backend: str, enable_checkpointing: bool) -> ProjectConfig:
    """Build a minimal valid ProjectConfig for the given backend and checkpointing flag."""
    return ProjectConfig(
        metadata=ProjectMetadata(
            name="test_project",
            description="Validator test",
            python_version="3.11",
            author="Test Author",
            email="test@example.com",
        ),
        agents=[
            AgentConfig(
                key="sql",
                class_name="SqlAgent",
                llm_model=LLMModel.GPT4O_MINI,
                system_prompt="You are a helpful assistant.",
                needs_validation=False,
            )
        ],
        database=DatabaseConfig(
            backend=DBBackend(backend),
            connection_env_var="DATABASE_URL",
            pool_size=5,
            max_overflow=10,
            use_alembic=False,
        ),
        workflow=WorkflowConfig(  # type: ignore[call-arg]
            default_intent="sql",
            enable_checkpointing=enable_checkpointing,
        ),
        enable_provider_registry=False,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_checkpointing_with_sqlite_raises():
    """enable_checkpointing=True with sqlite must raise a ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        _make_config("sqlite", enable_checkpointing=True)

    errors = exc_info.value.errors()
    messages = [e["msg"] for e in errors]
    assert any("postgres" in m for m in messages), (
        f"Expected error message mentioning 'postgres', got: {messages}"
    )
    assert any("sqlite" in m for m in messages), (
        f"Expected error message mentioning 'sqlite', got: {messages}"
    )


def test_checkpointing_with_mysql_raises():
    """enable_checkpointing=True with mysql must raise a ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        _make_config("mysql", enable_checkpointing=True)

    errors = exc_info.value.errors()
    messages = [e["msg"] for e in errors]
    assert any("postgres" in m for m in messages), (
        f"Expected error message mentioning 'postgres', got: {messages}"
    )
    assert any("mysql" in m for m in messages), (
        f"Expected error message mentioning 'mysql', got: {messages}"
    )


def test_checkpointing_with_postgres_is_valid():
    """enable_checkpointing=True with postgres must not raise."""
    config = _make_config("postgres", enable_checkpointing=True)
    assert config.workflow.enable_checkpointing is True
    assert config.database.backend == DBBackend.POSTGRES


def test_no_checkpointing_with_sqlite_is_valid():
    """enable_checkpointing=False (default) with sqlite must not raise."""
    config = _make_config("sqlite", enable_checkpointing=False)
    assert config.workflow.enable_checkpointing is False
    assert config.database.backend == DBBackend.SQLITE


def test_default_checkpointing_is_false():
    """WorkflowConfig.enable_checkpointing defaults to False."""
    wf = WorkflowConfig(default_intent="sql")  # type: ignore[call-arg]
    assert wf.enable_checkpointing is False


def test_error_message_is_actionable():
    """The validation error message must name both the required and actual backend."""
    with pytest.raises(ValidationError) as exc_info:
        _make_config("sqlite", enable_checkpointing=True)

    full_text = str(exc_info.value)
    assert "postgres" in full_text
    assert "sqlite" in full_text
