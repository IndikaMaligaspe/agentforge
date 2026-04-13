"""
Tests for JWT auth scaffold template rendering (TODO-8).

Covers:
- The 3 JWT-only files absent when auth_type != "jwt".
- All 4 JWT files present when auth_type == "jwt".
- Rendered jwt.py compiles without errors.
- No "madgicx" string (case-insensitive) in any rendered file.
- .env.example includes JWT_SECRET= for HS256, does NOT for RS256.
- pyproject.toml includes pyjwt[crypto] only when auth_type == "jwt".
- jwt.py / jwt_settings.py use template context vars (issuer/audience as
  defaults), not hardcoded strings.
- backend/security/__init__.py uses the JWT auth_init when auth_type=="jwt"
  (exports verify_token), and the plain __init__ otherwise.
"""
import ast
import pytest

from agentforge.engine.renderer import TemplateRenderer
from agentforge.schema.models import (
    AgentConfig, DatabaseConfig, LLMModel, ProjectConfig,
    ProjectMetadata, SecurityConfig, WorkflowConfig,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_config(
    auth_type: str = "none",
    jwt_algorithm: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
    jwks_url: str | None = None,
) -> ProjectConfig:
    """Build a minimal valid ProjectConfig for JWT render tests."""
    return ProjectConfig(
        metadata=ProjectMetadata(
            name="test_project",
            description="JWT render test",
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
        database=DatabaseConfig(backend="postgres"),  # type: ignore[call-arg]
        workflow=WorkflowConfig(default_intent="sql"),  # type: ignore[call-arg]
        security=SecurityConfig(
            auth_type=auth_type,  # type: ignore[arg-type]
            jwt_algorithm=jwt_algorithm,  # type: ignore[arg-type]
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
            jwks_url=jwks_url,
        ),
        enable_provider_registry=False,
    )


def _render_map(config: ProjectConfig) -> dict[str, str]:
    """Render all templates and return a {relative_path: content} mapping."""
    renderer = TemplateRenderer()
    return {str(path): content for path, content in renderer.render_all(config)}


# Files that only appear when auth_type == "jwt"
JWT_ONLY_FILES = {
    "backend/security/jwt.py",
    "backend/security/dtos.py",
    "backend/security/jwt_settings.py",
}

# The __init__ is always present but its content differs for JWT vs non-JWT
SECURITY_INIT = "backend/security/__init__.py"

# All 4 files together (for presence checks when JWT is enabled)
ALL_JWT_FILES = JWT_ONLY_FILES | {SECURITY_INIT}


# ── File presence predicates ──────────────────────────────────────────────────

@pytest.mark.parametrize("auth_type", ["none", "api_key"])
def test_jwt_only_files_absent_when_not_jwt(auth_type: str):
    """jwt.py, dtos.py, jwt_settings.py must be absent when auth_type is not 'jwt'."""
    rendered = _render_map(_make_config(auth_type=auth_type))
    for path in JWT_ONLY_FILES:
        assert path not in rendered, (
            f"Expected {path} to be absent for auth_type={auth_type}"
        )


def test_jwt_files_present_when_auth_type_jwt_hs256():
    """All 4 JWT files must be present when auth_type='jwt' with HS256."""
    rendered = _render_map(_make_config(auth_type="jwt", jwt_algorithm="HS256"))
    for path in ALL_JWT_FILES:
        assert path in rendered, f"Expected {path} to be present for JWT/HS256"


def test_jwt_files_present_when_auth_type_jwt_rs256():
    """All 4 JWT files must be present when auth_type='jwt' with RS256."""
    rendered = _render_map(
        _make_config(
            auth_type="jwt",
            jwt_algorithm="RS256",
            jwks_url="https://example.com/.well-known/jwks.json",
        )
    )
    for path in ALL_JWT_FILES:
        assert path in rendered, f"Expected {path} to be present for JWT/RS256"


def test_security_init_uses_plain_template_when_not_jwt():
    """backend/security/__init__.py must NOT export verify_token when auth_type != 'jwt'."""
    rendered = _render_map(_make_config(auth_type="none"))
    init = rendered[SECURITY_INIT]
    assert "verify_token" not in init


# ── Compile check ─────────────────────────────────────────────────────────────

def test_rendered_jwt_py_compiles_hs256():
    """Rendered backend/security/jwt.py must be valid Python (HS256 path)."""
    rendered = _render_map(_make_config(auth_type="jwt", jwt_algorithm="HS256"))
    source = rendered["backend/security/jwt.py"]
    try:
        ast.parse(source)
    except SyntaxError as e:
        pytest.fail(f"backend/security/jwt.py has a syntax error (HS256): {e}\n\n{source}")


def test_rendered_jwt_py_compiles_rs256():
    """Rendered backend/security/jwt.py must be valid Python (RS256 path)."""
    rendered = _render_map(
        _make_config(
            auth_type="jwt",
            jwt_algorithm="RS256",
            jwks_url="https://example.com/.well-known/jwks.json",
        )
    )
    source = rendered["backend/security/jwt.py"]
    try:
        ast.parse(source)
    except SyntaxError as e:
        pytest.fail(f"backend/security/jwt.py has a syntax error (RS256): {e}\n\n{source}")


def test_rendered_dtos_compiles():
    """Rendered backend/security/dtos.py must be valid Python."""
    rendered = _render_map(_make_config(auth_type="jwt", jwt_algorithm="HS256"))
    source = rendered["backend/security/dtos.py"]
    try:
        ast.parse(source)
    except SyntaxError as e:
        pytest.fail(f"backend/security/dtos.py has a syntax error: {e}\n\n{source}")


def test_rendered_jwt_settings_compiles_hs256():
    """Rendered backend/security/jwt_settings.py must be valid Python (HS256)."""
    rendered = _render_map(_make_config(auth_type="jwt", jwt_algorithm="HS256"))
    source = rendered["backend/security/jwt_settings.py"]
    try:
        ast.parse(source)
    except SyntaxError as e:
        pytest.fail(f"backend/security/jwt_settings.py has a syntax error (HS256): {e}\n\n{source}")


def test_rendered_jwt_settings_compiles_rs256():
    """Rendered backend/security/jwt_settings.py must be valid Python (RS256)."""
    rendered = _render_map(
        _make_config(
            auth_type="jwt",
            jwt_algorithm="RS256",
            jwks_url="https://example.com/.well-known/jwks.json",
        )
    )
    source = rendered["backend/security/jwt_settings.py"]
    try:
        ast.parse(source)
    except SyntaxError as e:
        pytest.fail(f"backend/security/jwt_settings.py has a syntax error (RS256): {e}\n\n{source}")


# ── No Madgicx strings ────────────────────────────────────────────────────────

@pytest.mark.parametrize("algorithm,extra_kwargs", [
    ("HS256", {}),
    ("RS256", {"jwks_url": "https://example.com/.well-known/jwks.json"}),
])
def test_no_madgicx_strings_in_rendered_output(algorithm: str, extra_kwargs: dict):
    """No rendered file must contain the string 'madgicx' (case-insensitive)."""
    rendered = _render_map(
        _make_config(auth_type="jwt", jwt_algorithm=algorithm, **extra_kwargs)
    )
    violations = []
    for path, content in rendered.items():
        if "madgicx" in content.lower():
            violations.append(path)
    assert not violations, (
        f"'madgicx' found in rendered files: {violations}. "
        "No Madgicx-specific strings may appear in generated output."
    )


# ── .env.example JWT_SECRET ───────────────────────────────────────────────────

def test_env_example_includes_jwt_secret_for_hs256():
    """.env.example must include JWT_SECRET= for HS256 algorithm."""
    rendered = _render_map(_make_config(auth_type="jwt", jwt_algorithm="HS256"))
    env = rendered[".env.example"]
    assert "JWT_SECRET=" in env, (
        "Expected JWT_SECRET= placeholder in .env.example for HS256"
    )


def test_env_example_excludes_jwt_secret_for_rs256():
    """.env.example must NOT include JWT_SECRET= for RS256 (JWKS fetched over HTTP)."""
    rendered = _render_map(
        _make_config(
            auth_type="jwt",
            jwt_algorithm="RS256",
            jwks_url="https://example.com/.well-known/jwks.json",
        )
    )
    env = rendered[".env.example"]
    assert "JWT_SECRET=" not in env, (
        "JWT_SECRET= must not appear in .env.example for RS256 (keys fetched via JWKS)"
    )


def test_env_example_no_jwt_secret_when_auth_type_none():
    """.env.example must NOT include JWT_SECRET= when auth_type='none'."""
    rendered = _render_map(_make_config(auth_type="none"))
    env = rendered[".env.example"]
    assert "JWT_SECRET=" not in env


# ── pyproject.toml dependencies ───────────────────────────────────────────────

def test_pyproject_includes_pyjwt_when_jwt():
    """pyproject.toml must include pyjwt[crypto] when auth_type='jwt'."""
    renderer = TemplateRenderer()
    config = _make_config(auth_type="jwt", jwt_algorithm="HS256")
    ctx = renderer._build_context(config)
    toml = renderer._env.get_template("pyproject.toml.j2").render(**ctx)
    assert "pyjwt[crypto]" in toml, "Expected pyjwt[crypto] in pyproject.toml for JWT"
    assert "httpx" in toml, "Expected httpx in pyproject.toml for JWT"


def test_pyproject_excludes_pyjwt_when_not_jwt():
    """pyproject.toml must NOT include pyjwt[crypto] when auth_type != 'jwt'."""
    renderer = TemplateRenderer()
    config = _make_config(auth_type="api_key")
    ctx = renderer._build_context(config)
    toml = renderer._env.get_template("pyproject.toml.j2").render(**ctx)
    assert "pyjwt" not in toml.lower(), (
        "pyjwt must not appear in pyproject.toml when auth_type is not 'jwt'"
    )


# ── Settings file context vars ────────────────────────────────────────────────

def test_jwt_settings_contains_issuer_when_set():
    """jwt_settings.py must embed the configured issuer as default."""
    rendered = _render_map(
        _make_config(
            auth_type="jwt",
            jwt_algorithm="HS256",
            jwt_issuer="https://auth.example.com/",
        )
    )
    settings = rendered["backend/security/jwt_settings.py"]
    assert "https://auth.example.com/" in settings


def test_jwt_settings_issuer_none_when_not_set():
    """jwt_settings.py must use None as default when no issuer configured."""
    rendered = _render_map(_make_config(auth_type="jwt", jwt_algorithm="HS256"))
    settings = rendered["backend/security/jwt_settings.py"]
    assert "None" in settings


def test_jwt_settings_audience_contains_value_when_set():
    """jwt_settings.py must embed the configured audience as default."""
    rendered = _render_map(
        _make_config(
            auth_type="jwt",
            jwt_algorithm="HS256",
            jwt_audience="my-api",
        )
    )
    settings = rendered["backend/security/jwt_settings.py"]
    assert "my-api" in settings


def test_jwt_settings_rs256_contains_jwks_url():
    """jwt_settings.py must embed the JWKS URL for RS256."""
    rendered = _render_map(
        _make_config(
            auth_type="jwt",
            jwt_algorithm="RS256",
            jwks_url="https://example.com/.well-known/jwks.json",
        )
    )
    settings = rendered["backend/security/jwt_settings.py"]
    assert "https://example.com/.well-known/jwks.json" in settings


# ── RS256 end-to-end scaffold ─────────────────────────────────────────────────

def test_rs256_full_scaffold_produces_importable_files():
    """All 4 JWT files for RS256 must compile without syntax errors."""
    config = _make_config(
        auth_type="jwt",
        jwt_algorithm="RS256",
        jwks_url="https://example.com/jwks",
    )
    rendered = _render_map(config)
    for path in ALL_JWT_FILES:
        assert path in rendered, f"Missing {path}"
        source = rendered[path]
        try:
            ast.parse(source)
        except SyntaxError as e:
            pytest.fail(f"{path} syntax error (RS256 e2e): {e}\n\n{source}")


# ── HS256 end-to-end scaffold ─────────────────────────────────────────────────

def test_hs256_full_scaffold_produces_importable_files():
    """All 4 JWT files for HS256 must compile without syntax errors."""
    config = _make_config(auth_type="jwt", jwt_algorithm="HS256")
    rendered = _render_map(config)
    for path in ALL_JWT_FILES:
        assert path in rendered, f"Missing {path}"
        source = rendered[path]
        try:
            ast.parse(source)
        except SyntaxError as e:
            pytest.fail(f"{path} syntax error (HS256 e2e): {e}\n\n{source}")


# ── auth_init __init__.py content ─────────────────────────────────────────────

def test_auth_init_exports_verify_token():
    """backend/security/__init__.py must export verify_token when JWT."""
    rendered = _render_map(_make_config(auth_type="jwt", jwt_algorithm="HS256"))
    init = rendered["backend/security/__init__.py"]
    assert "verify_token" in init
    assert "AuthError" in init
