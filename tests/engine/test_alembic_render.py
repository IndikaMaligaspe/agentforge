"""
Tests for Alembic migration scaffold rendering (TODO-1).

Covers:
- Per-backend rendering snapshot (postgres, mysql, sqlite).
- Schema validation: invalid backend rejected.
- docker-compose.yml renders correct DB service per backend.
- sqlite projects do not emit a docker-compose DB service.
- use_alembic=False suppresses all three alembic output files.
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
from agentforge.engine.renderer import TemplateRenderer


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_config(backend: str, use_alembic: bool = True) -> ProjectConfig:
    """Build a minimal valid ProjectConfig for the given backend."""
    return ProjectConfig(
        metadata=ProjectMetadata(
            name="test_project",
            description="Alembic render test",
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
            use_alembic=use_alembic,
        ),
        workflow=WorkflowConfig(default_intent="sql"),  # type: ignore[call-arg]
        enable_provider_registry=False,
    )


def _render_map(config: ProjectConfig) -> dict[str, str]:
    """Render all templates and return a {relative_path: content} mapping."""
    renderer = TemplateRenderer()
    return {str(path): content for path, content in renderer.render_all(config)}


# ── Schema validation ─────────────────────────────────────────────────────────

def test_use_alembic_defaults_false():
    """DatabaseConfig.use_alembic must default to False."""
    db = DatabaseConfig(backend=DBBackend.POSTGRES, connection_env_var="DATABASE_URL", pool_size=5, max_overflow=10)  # type: ignore[call-arg]
    assert db.use_alembic is False


def test_use_alembic_can_be_set_true():
    db = DatabaseConfig(backend=DBBackend.POSTGRES, connection_env_var="DATABASE_URL", pool_size=5, max_overflow=10, use_alembic=True)
    assert db.use_alembic is True


def test_invalid_backend_rejected():
    """An unsupported backend string must raise a ValidationError."""
    with pytest.raises(ValidationError):
        DatabaseConfig(backend="oracle")  # type: ignore[arg-type]


# ── Alembic files emitted only when use_alembic=True ─────────────────────────

ALEMBIC_PATHS = {
    "alembic.ini",
    "backend/migrations/env.py",
    "backend/migrations/script.py.mako",
}


@pytest.mark.parametrize("backend", ["postgres", "mysql", "sqlite"])
def test_alembic_files_present_when_enabled(backend):
    """All three alembic output files must appear when use_alembic=True."""
    rendered = _render_map(_make_config(backend, use_alembic=True))
    for path in ALEMBIC_PATHS:
        assert path in rendered, f"Expected {path} for backend={backend}"


@pytest.mark.parametrize("backend", ["postgres", "mysql", "sqlite"])
def test_alembic_files_absent_when_disabled(backend):
    """No alembic output files must appear when use_alembic=False."""
    rendered = _render_map(_make_config(backend, use_alembic=False))
    for path in ALEMBIC_PATHS:
        assert path not in rendered, f"Unexpected {path} for backend={backend} with use_alembic=False"


# ── alembic.ini content ───────────────────────────────────────────────────────

@pytest.mark.parametrize("backend", ["postgres", "mysql", "sqlite"])
def test_alembic_ini_script_location(backend):
    """alembic.ini must point script_location at backend/migrations."""
    rendered = _render_map(_make_config(backend, use_alembic=True))
    ini = rendered["alembic.ini"]
    assert "script_location = backend/migrations" in ini


# ── env.py content ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("backend", ["postgres", "mysql", "sqlite"])
def test_env_py_reads_env_var(backend):
    """env.py must read the DB URL from the configured env var name."""
    rendered = _render_map(_make_config(backend, use_alembic=True))
    env_py = rendered["backend/migrations/env.py"]
    assert "DATABASE_URL" in env_py


def test_env_py_uses_sync_engine():
    """env.py must use synchronous engine_from_config (not async)."""
    rendered = _render_map(_make_config("postgres", use_alembic=True))
    env_py = rendered["backend/migrations/env.py"]
    assert "engine_from_config" in env_py
    assert "async_engine_from_config" not in env_py


def test_env_py_raises_on_missing_db_url():
    """env.py must raise RuntimeError when DATABASE_URL is not set (not KeyError)."""
    rendered = _render_map(_make_config("postgres", use_alembic=True))
    env_py = rendered["backend/migrations/env.py"]
    assert "RuntimeError" in env_py
    assert "is not set; cannot run Alembic migrations" in env_py
    # os.environ.get() must be used — not the bare key-access form that raises KeyError
    assert "os.environ.get(" in env_py
    assert 'os.environ["DATABASE_URL"]' not in env_py


def test_env_py_raises_on_missing_base():
    """env.py must raise RuntimeError (not silently set target_metadata=None) when Base import fails."""
    rendered = _render_map(_make_config("postgres", use_alembic=True))
    env_py = rendered["backend/migrations/env.py"]
    assert "RuntimeError" in env_py
    assert "backend/db/base.py" in env_py
    # The silent fallback must not appear
    assert "target_metadata = None" not in env_py


# ── script.py.mako content ────────────────────────────────────────────────────

@pytest.mark.parametrize("backend", ["postgres", "mysql", "sqlite"])
def test_script_mako_contains_mako_expressions(backend):
    """script.py.mako must contain literal Mako ${...} expressions (not rendered by Jinja2)."""
    rendered = _render_map(_make_config(backend, use_alembic=True))
    mako = rendered["backend/migrations/script.py.mako"]
    assert "${message}" in mako
    assert "${up_revision}" in mako
    assert "def upgrade" in mako
    assert "def downgrade" in mako


# ── docker-compose.yml per backend ────────────────────────────────────────────

def test_docker_compose_postgres_has_db_service():
    """postgres backend must include a postgres db service."""
    rendered = _render_map(_make_config("postgres", use_alembic=False))
    dc = rendered["docker-compose.yml"] if "docker-compose.yml" in rendered else ""
    # docker-compose is always rendered via env.j2 path; check via renderer directly
    renderer = TemplateRenderer()
    config = _make_config("postgres", use_alembic=False)
    ctx = renderer._build_context(config)
    tmpl = renderer._env.get_template("docker-compose.yml.j2")
    content = tmpl.render(**ctx)
    assert "postgres:15-alpine" in content
    assert "depends_on" in content


def test_docker_compose_mysql_has_db_service():
    """mysql backend must include a mysql db service."""
    renderer = TemplateRenderer()
    config = _make_config("mysql", use_alembic=False)
    ctx = renderer._build_context(config)
    tmpl = renderer._env.get_template("docker-compose.yml.j2")
    content = tmpl.render(**ctx)
    assert "mysql:8" in content
    assert "depends_on" in content


def test_docker_compose_sqlite_has_no_db_service():
    """sqlite backend must NOT include a db service or depends_on."""
    renderer = TemplateRenderer()
    config = _make_config("sqlite", use_alembic=False)
    ctx = renderer._build_context(config)
    tmpl = renderer._env.get_template("docker-compose.yml.j2")
    content = tmpl.render(**ctx)
    assert "image: postgres" not in content
    assert "image: mysql" not in content
    assert "depends_on" not in content


# ── .env.example driver strings ───────────────────────────────────────────────

@pytest.mark.parametrize("backend, expected_driver", [
    ("postgres", "postgresql+psycopg://"),
    ("mysql", "mysql+pymysql://"),
    ("sqlite", "sqlite:///./app.db"),
])
def test_env_driver_string(backend: str, expected_driver: str):
    """.env.example must use the correct driver URL scheme for each backend."""
    renderer = TemplateRenderer()
    config = _make_config(backend, use_alembic=False)
    ctx = renderer._build_context(config)
    tmpl = renderer._env.get_template(".env.example.j2")
    content = tmpl.render(**ctx)
    assert expected_driver in content


# ── pyproject.toml driver dependencies ────────────────────────────────────────

@pytest.mark.parametrize("backend, expected_present, expected_absent", [
    ("postgres", ["psycopg[binary]", "alembic"], []),
    ("mysql", ["pymysql", "alembic"], ["mysqlclient"]),
    ("sqlite", ["alembic"], ["psycopg", "pymysql"]),
])
def test_pyproject_driver_dep(backend: str, expected_present: list, expected_absent: list):
    """pyproject.toml must list the correct driver dependencies per backend."""
    renderer = TemplateRenderer()
    config = _make_config(backend, use_alembic=True)
    ctx = renderer._build_context(config)
    tmpl = renderer._env.get_template("pyproject.toml.j2")
    content = tmpl.render(**ctx)
    for dep in expected_present:
        assert dep in content, f"Expected '{dep}' in pyproject.toml for backend={backend}"
    for dep in expected_absent:
        assert dep not in content, f"'{dep}' must not appear in pyproject.toml for backend={backend}"


def test_pyproject_alembic_always_present():
    """alembic must be in pyproject.toml regardless of use_alembic flag."""
    for backend in ["postgres", "mysql", "sqlite"]:
        renderer = TemplateRenderer()
        config = _make_config(backend, use_alembic=False)
        ctx = renderer._build_context(config)
        tmpl = renderer._env.get_template("pyproject.toml.j2")
        content = tmpl.render(**ctx)
        assert "alembic" in content, f"alembic missing for backend={backend}"


def test_pyproject_author_email_matches_config():
    """pyproject.toml must contain a non-empty author email matching the input config."""
    renderer = TemplateRenderer()
    config = _make_config("postgres", use_alembic=False)
    ctx = renderer._build_context(config)
    tmpl = renderer._env.get_template("pyproject.toml.j2")
    content = tmpl.render(**ctx)
    # The email from ProjectMetadata must appear verbatim in the authors table.
    assert 'email = "test@example.com"' in content
    # Guard: author_email alias must be non-empty in the render context.
    assert ctx["author_email"] == "test@example.com"
