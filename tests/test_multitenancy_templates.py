"""Tests for multi-tenancy conditional template emission.

Verifies the render contract for the four multi-tenancy scaffolded files:
  - backend/config/settings.py          (enabled=True always)
  - backend/services/credential_provider.py  (enabled=True always)
  - backend/services/platform_db.py     (enabled=True AND credential_provider='db')
  - backend/middleware/account_gate.py   (enabled=True always)

Five cases:
1. multi_tenancy.enabled=False (default) — none of the four templates emitted.
2. enabled=True, credential_provider='env' — 3 of 4 emitted (no platform_db).
3. enabled=True, credential_provider='db'  — all 4 emitted.
4. All 4 emitted files pass ast.parse.
5. enabled=True with auth_type != 'jwt' fires a UserWarning about anonymous tenants.
"""
import ast
import warnings
from pathlib import Path

from agentforge.schema.loader import load
from agentforge.schema.models import ProjectConfig
from agentforge.engine.renderer import TemplateRenderer

FIXTURES_DIR = Path(__file__).parent / "fixtures"

_SETTINGS_KEY          = "backend/config/settings.py"
_CREDENTIAL_KEY        = "backend/services/credential_provider.py"
_PLATFORM_DB_KEY       = "backend/services/platform_db.py"
_ACCOUNT_GATE_KEY      = "backend/middleware/account_gate.py"

_ALL_MT_KEYS = [
    _SETTINGS_KEY,
    _CREDENTIAL_KEY,
    _PLATFORM_DB_KEY,
    _ACCOUNT_GATE_KEY,
]


def _render_dict(config) -> dict[str, str]:
    """Return render_all output as a dict keyed by str(path)."""
    return {str(path): content for path, content in TemplateRenderer().render_all(config)}


def test_multitenancy_disabled_emits_no_new_templates():
    """Default flags: none of the multi-tenancy templates are rendered.

    full.yaml does not set multi_tenancy, so the default MultiTenancyConfig
    has enabled=False.  None of the four guarded templates should appear.
    """
    config = load(FIXTURES_DIR / "full.yaml")

    files = _render_dict(config)

    for key in _ALL_MT_KEYS:
        assert key not in files, (
            f"Expected {key!r} to be absent from rendered output when "
            "multi_tenancy.enabled=False (default)"
        )


def test_multitenancy_env_provider_emits_3_templates():
    """enabled=True, credential_provider='env' emits 3 of 4 (no platform_db).

    platform_db.py is only emitted when the credential_provider is 'db'
    (it provides the asyncpg pool used for per-tenant DB credential lookups).
    The env provider reads credentials from environment variables and does
    not need a platform DB connection.

    auth_type is overridden to 'jwt' to suppress the anonymous-tenant warning
    (keeping this test focused on the emission logic only).
    """
    base = load(FIXTURES_DIR / "full.yaml")
    new_sec = base.security.model_copy(update={"auth_type": "jwt", "jwt_algorithm": "HS256"})
    new_mt  = base.multi_tenancy.model_copy(update={"enabled": True, "credential_provider": "env"})
    config  = base.model_copy(update={"security": new_sec, "multi_tenancy": new_mt})

    files = _render_dict(config)

    for key in [_SETTINGS_KEY, _CREDENTIAL_KEY, _ACCOUNT_GATE_KEY]:
        assert key in files, (
            f"Expected {key!r} in rendered output when "
            "multi_tenancy.enabled=True, credential_provider='env'"
        )

    assert _PLATFORM_DB_KEY not in files, (
        f"Expected {_PLATFORM_DB_KEY!r} to be absent from rendered output when "
        "credential_provider='env' (platform_db is only needed for the 'db' provider)"
    )


def test_multitenancy_db_provider_emits_all_4_templates():
    """enabled=True, credential_provider='db' emits all 4 templates.

    auth_type is overridden to 'jwt' to suppress the anonymous-tenant warning.
    """
    base = load(FIXTURES_DIR / "full.yaml")
    new_sec = base.security.model_copy(update={"auth_type": "jwt", "jwt_algorithm": "HS256"})
    new_mt  = base.multi_tenancy.model_copy(update={"enabled": True, "credential_provider": "db"})
    config  = base.model_copy(update={"security": new_sec, "multi_tenancy": new_mt})

    files = _render_dict(config)

    for key in _ALL_MT_KEYS:
        assert key in files, (
            f"Expected {key!r} in rendered output when "
            "multi_tenancy.enabled=True, credential_provider='db'"
        )


def test_multitenancy_emitted_files_are_valid_python():
    """All 4 multi-tenancy templates render to syntactically valid Python.

    Uses the 'db' scenario (emits all 4 files). Parses each with ast.parse,
    which raises SyntaxError if the Jinja2 template produces invalid Python.
    auth_type is overridden to 'jwt' to suppress the anonymous-tenant warning.
    """
    base = load(FIXTURES_DIR / "full.yaml")
    new_sec = base.security.model_copy(update={"auth_type": "jwt", "jwt_algorithm": "HS256"})
    new_mt  = base.multi_tenancy.model_copy(update={"enabled": True, "credential_provider": "db"})
    config  = base.model_copy(update={"security": new_sec, "multi_tenancy": new_mt})

    files = _render_dict(config)

    for key in _ALL_MT_KEYS:
        assert key in files, (
            f"Expected {key!r} to be present in rendered output for ast.parse check"
        )
        ast.parse(files[key])  # raises SyntaxError if rendered output is invalid Python


def test_multitenancy_without_jwt_warns():
    """multi_tenancy.enabled=True with auth_type != 'jwt' fires a UserWarning.

    full.yaml defaults to auth_type='api_key'.  When multi_tenancy.enabled is
    set to True without also switching to JWT, the ProjectConfig model_validator
    _warn_multi_tenancy_without_jwt fires a UserWarning about anonymous tenants.

    Note: Pydantic v2 model_copy() does NOT re-run model_validator(mode="after")
    validators on the parent model.  The warning only fires during initial model
    construction via model_validate() / __init__.  We therefore mutate a dict
    and call ProjectConfig.model_validate() directly to exercise the validator.
    """
    base = load(FIXTURES_DIR / "full.yaml")

    # full.yaml has auth_type='api_key' — no override needed to trigger the warning.
    data = base.model_dump()
    data["multi_tenancy"]["enabled"] = True

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        ProjectConfig.model_validate(data)

    assert any(
        issubclass(w.category, UserWarning) and "anonymous tenants" in str(w.message)
        for w in captured
    ), f"Expected UserWarning with 'anonymous tenants' in message, got: {[str(w.message) for w in captured]}"
