"""
Tests for JWT auth scaffold template rendering (TODO-8).

Covers:
- The 3 JWT-only files absent when auth_type != "jwt".
- All 4 JWT files present when auth_type == "jwt".
- Rendered jwt.py compiles without errors.
- No "madgicx" string (case-insensitive) in any rendered file.
- .env.example includes JWT_SECRET= for HS256, does NOT for RS256.
- requirements.txt includes pyjwt[crypto] only when auth_type == "jwt".
- jwt.py / jwt_settings.py use template context vars (issuer/audience as
  defaults), not hardcoded strings.
- backend/security/__init__.py uses the JWT auth_init when auth_type=="jwt"
  (exports verify_token), and the plain __init__ otherwise.
- backend/security/auth.py absent when auth_type=="jwt", present for api_key.
- main.py imports verify_token when jwt, get_api_key when api_key.
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

def test_env_includes_jwt_secret_for_hs256():
    """Rendered .env.example must include JWT_SECRET= when auth_type=jwt and HS256."""
    rendered = _render_map(_make_config(auth_type="jwt", jwt_algorithm="HS256"))
    env = rendered[".env.example"]
    assert "JWT_SECRET=" in env, "Expected JWT_SECRET= in .env.example for HS256"


def test_env_excludes_jwt_secret_for_rs256():
    """Rendered .env.example must NOT include JWT_SECRET= when RS256 (JWKS-based)."""
    rendered = _render_map(
        _make_config(
            auth_type="jwt",
            jwt_algorithm="RS256",
            jwks_url="https://example.com/.well-known/jwks.json",
        )
    )
    env = rendered[".env.example"]
    assert "JWT_SECRET=" not in env, "JWT_SECRET= must be absent for RS256"


def test_env_excludes_jwt_secret_for_api_key():
    """Rendered .env.example must NOT include JWT_SECRET= when auth_type=api_key."""
    rendered = _render_map(_make_config(auth_type="api_key"))
    env = rendered[".env.example"]
    assert "JWT_SECRET=" not in env, "JWT_SECRET= must be absent for api_key"


# ── requirements.txt dependencies ─────────────────────────────────────────────

def test_requirements_txt_includes_pyjwt_when_jwt():
    """requirements.txt must include pyjwt[crypto] when auth_type='jwt'."""
    rendered = _render_map(_make_config(auth_type="jwt", jwt_algorithm="HS256"))
    assert "requirements.txt" in rendered
    req = rendered["requirements.txt"]
    assert "pyjwt[crypto]" in req, "Expected pyjwt[crypto] in requirements.txt for JWT"


def test_requirements_txt_omits_pyjwt_when_not_jwt():
    """requirements.txt must NOT include pyjwt when auth_type != 'jwt'."""
    rendered = _render_map(_make_config(auth_type="api_key"))
    assert "requirements.txt" in rendered
    req = rendered["requirements.txt"]
    assert "pyjwt" not in req.lower(), (
        "pyjwt must not appear in requirements.txt when auth_type is not 'jwt'"
    )


# ── pyproject.toml dependencies ───────────────────────────────────────────────

def test_pyproject_includes_pyjwt_when_jwt():
    """pyproject.toml must include pyjwt[crypto] when auth_type='jwt'."""
    renderer = TemplateRenderer()
    config = _make_config(auth_type="jwt", jwt_algorithm="HS256")
    ctx = renderer._build_context(config)
    toml = renderer._env.get_template("pyproject.toml.j2").render(**ctx)
    assert "pyjwt[crypto]" in toml, "Expected pyjwt[crypto] in pyproject.toml for JWT"


def test_pyproject_excludes_pyjwt_when_not_jwt():
    """pyproject.toml must NOT include pyjwt[crypto] when auth_type != 'jwt'."""
    renderer = TemplateRenderer()
    config = _make_config(auth_type="api_key")
    ctx = renderer._build_context(config)
    toml = renderer._env.get_template("pyproject.toml.j2").render(**ctx)
    assert "pyjwt" not in toml.lower(), (
        "pyjwt must not appear in pyproject.toml when auth_type is not 'jwt'"
    )


# ── main.py auth import ───────────────────────────────────────────────────────

def test_main_py_uses_verify_token_when_jwt():
    """Rendered main.py must import verify_token and not get_api_key when auth_type='jwt'."""
    rendered = _render_map(_make_config(auth_type="jwt", jwt_algorithm="HS256"))
    main = rendered["backend/main.py"]
    assert "verify_token" in main, "Expected verify_token import in main.py for JWT"
    assert "get_api_key" not in main, "get_api_key must not appear in main.py for JWT"


def test_main_py_uses_get_api_key_when_api_key():
    """Rendered main.py must import get_api_key and not verify_token when auth_type='api_key'."""
    rendered = _render_map(_make_config(auth_type="api_key"))
    main = rendered["backend/main.py"]
    assert "get_api_key" in main, "Expected get_api_key import in main.py for api_key"
    assert "verify_token" not in main, "verify_token must not appear in main.py for api_key"


# ── auth.py presence gating ───────────────────────────────────────────────────

def test_auth_py_absent_when_jwt():
    """backend/security/auth.py must NOT be rendered when auth_type='jwt'."""
    rendered = _render_map(_make_config(auth_type="jwt", jwt_algorithm="HS256"))
    assert "backend/security/auth.py" not in rendered, (
        "backend/security/auth.py must be absent for JWT projects"
    )


def test_auth_py_present_when_api_key():
    """backend/security/auth.py must be rendered when auth_type='api_key'."""
    rendered = _render_map(_make_config(auth_type="api_key"))
    assert "backend/security/auth.py" in rendered, (
        "backend/security/auth.py must be present for api_key projects"
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
