"""Tests for security.auth_type — conditional emission of
backend/middleware/permission_gate.py."""
import ast
from pathlib import Path

from agentforge.schema.loader import load
from agentforge.engine.renderer import TemplateRenderer

FIXTURES_DIR = Path(__file__).parent / "fixtures"

_GATE_KEY = "backend/middleware/permission_gate.py"


def _render_dict(config) -> dict[str, str]:
    """Return render_all output as a dict keyed by str(path)."""
    return {str(path): content for path, content in TemplateRenderer().render_all(config)}


def test_permission_gate_emitted_for_jwt():
    """auth_type='jwt' must render permission_gate.py as valid Python."""
    base = load(FIXTURES_DIR / "full.yaml")
    new_sec = base.security.model_copy(update={"auth_type": "jwt", "jwt_algorithm": "HS256"})
    config = base.model_copy(update={"security": new_sec})

    files = _render_dict(config)

    assert _GATE_KEY in files, (
        f"Expected {_GATE_KEY!r} in rendered output when auth_type='jwt'"
    )
    ast.parse(files[_GATE_KEY])  # raises SyntaxError if the rendered file is invalid Python


def test_permission_gate_not_emitted_for_api_key():
    """auth_type='api_key' (default in full.yaml) must NOT render permission_gate.py."""
    config = load(FIXTURES_DIR / "full.yaml")

    files = _render_dict(config)

    assert _GATE_KEY not in files, (
        f"Expected {_GATE_KEY!r} to be absent from rendered output when auth_type='api_key'"
    )


def test_permission_gate_contains_substring_bypass_guard():
    """When emitted, the rendered file MUST contain the substring-bypass guard.

    This test locks the critical security property: claims['permissions'] must be
    verified as a list before membership testing, preventing string-substring bypass
    (e.g. 'adm' in 'admin' is True).  If someone removes or rewrites this guard,
    this test will catch the regression.
    """
    base = load(FIXTURES_DIR / "full.yaml")
    new_sec = base.security.model_copy(update={"auth_type": "jwt", "jwt_algorithm": "HS256"})
    config = base.model_copy(update={"security": new_sec})

    files = _render_dict(config)
    gate_py = files[_GATE_KEY]

    assert "if not isinstance(raw, list):" in gate_py, (
        "Substring-bypass guard 'if not isinstance(raw, list):' is missing from "
        "the rendered permission_gate.py — this is a critical security regression."
    )


def test_permission_gate_contains_require_permission_symbol():
    """When emitted, the rendered file must define the require_permission factory."""
    base = load(FIXTURES_DIR / "full.yaml")
    new_sec = base.security.model_copy(update={"auth_type": "jwt", "jwt_algorithm": "HS256"})
    config = base.model_copy(update={"security": new_sec})

    files = _render_dict(config)
    gate_py = files[_GATE_KEY]

    assert "def require_permission(" in gate_py, (
        "Expected 'def require_permission(' to be present in rendered permission_gate.py"
    )
