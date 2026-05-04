"""Tests for structlog context binding in backend/security/jwt.py.

Verifies that bind_contextvars is injected into verify_token only when
both auth_type='jwt' AND structured_logging=True are set.  Three cases:

1. Both flags on  — binding is present, file is valid Python.
2. structured_logging off — binding is absent, file is valid Python.
3. auth_type='api_key' — jwt.py is not emitted at all.
"""
import ast
from pathlib import Path

from agentforge.schema.loader import load
from agentforge.engine.renderer import TemplateRenderer

FIXTURES_DIR = Path(__file__).parent / "fixtures"

_JWT_KEY = "backend/security/jwt.py"


def _render_dict(config) -> dict[str, str]:
    """Return render_all output as a dict keyed by str(path)."""
    return {str(path): content for path, content in TemplateRenderer().render_all(config)}


def test_bind_contextvars_present_when_jwt_and_structured_logging_on():
    """auth_type='jwt' + structured_logging=True must inject bind_contextvars."""
    base = load(FIXTURES_DIR / "full.yaml")
    new_sec = base.security.model_copy(update={"auth_type": "jwt", "jwt_algorithm": "HS256"})
    new_obs = base.observability.model_copy(update={"structured_logging": True})
    config = base.model_copy(update={"security": new_sec, "observability": new_obs})

    files = _render_dict(config)

    assert _JWT_KEY in files, (
        f"Expected {_JWT_KEY!r} in rendered output when auth_type='jwt'"
    )
    jwt_py = files[_JWT_KEY]
    assert "bind_contextvars" in jwt_py, (
        "Expected 'bind_contextvars' in rendered jwt.py when structured_logging=True"
    )
    ast.parse(jwt_py)  # raises SyntaxError if the rendered file is invalid Python


def test_bind_contextvars_absent_when_structured_logging_off():
    """auth_type='jwt' + structured_logging=False must NOT inject bind_contextvars."""
    base = load(FIXTURES_DIR / "full.yaml")
    new_sec = base.security.model_copy(update={"auth_type": "jwt", "jwt_algorithm": "HS256"})
    new_obs = base.observability.model_copy(update={"structured_logging": False})
    config = base.model_copy(update={"security": new_sec, "observability": new_obs})

    files = _render_dict(config)

    assert _JWT_KEY in files, (
        f"Expected {_JWT_KEY!r} in rendered output when auth_type='jwt'"
    )
    jwt_py = files[_JWT_KEY]
    assert "bind_contextvars" not in jwt_py, (
        "Expected 'bind_contextvars' to be absent from rendered jwt.py when structured_logging=False"
    )
    ast.parse(jwt_py)  # raises SyntaxError if the rendered file is invalid Python


def test_jwt_py_not_emitted_for_api_key_auth():
    """auth_type='api_key' (default in full.yaml) must NOT render backend/security/jwt.py."""
    config = load(FIXTURES_DIR / "full.yaml")

    files = _render_dict(config)

    assert _JWT_KEY not in files, (
        f"Expected {_JWT_KEY!r} to be absent from rendered output when auth_type='api_key'"
    )
