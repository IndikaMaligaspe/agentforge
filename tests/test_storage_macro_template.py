"""Tests for the storage macro render contract.

Verifies that the per-store template (store_backend.py.j2) and the shared
BigQuery REST client (services/bigquery_rest_client.py.j2) are emitted — or
suppressed — correctly based on the StoreSpec list in ProjectConfig.stores.

Five cases:

1. Empty stores list → no store files, no bigquery client.
2. One store with memory + bigquery backends → per-store file AND bigquery client.
3. One store with only memory backend → per-store file, NO bigquery client.
4. Sanity: stores=[] (same as case 1) → no store-related files (byte-identity guard).
5. PascalCase / snake_case correctness for a multi-word store name ("user_profile").
"""
import ast
from pathlib import Path

from agentforge.schema.loader import load
from agentforge.engine.renderer import TemplateRenderer
from agentforge.schema.models import StoreSpec

FIXTURES_DIR = Path(__file__).parent / "fixtures"

_BQ_KEY = "backend/services/bigquery_rest_client.py"


def _render_dict(config) -> dict[str, str]:
    """Return render_all output as a dict keyed by str(path)."""
    return {str(path): content for path, content in TemplateRenderer().render_all(config)}


def _store_key(name: str) -> str:
    return f"backend/services/{name}_store.py"


# ── Test 1 ────────────────────────────────────────────────────────────────────

def test_empty_stores_emits_no_store_files():
    """With stores=[] (default in full.yaml), no store or bigquery files are emitted."""
    config = load(FIXTURES_DIR / "full.yaml")
    # Confirm the fixture truly has an empty stores list.
    assert config.stores == [], "Test precondition: full.yaml must have stores=[]"

    files = _render_dict(config)

    # No backend/services/*_store.py path should appear.
    store_paths = [k for k in files if k.startswith("backend/services/") and k.endswith("_store.py")]
    assert store_paths == [], (
        f"Expected no *_store.py files when stores=[]; got: {store_paths}"
    )
    assert _BQ_KEY not in files, (
        f"Expected {_BQ_KEY!r} to be absent when stores=[]"
    )


# ── Test 2 ────────────────────────────────────────────────────────────────────

def test_store_with_bigquery_backend_emits_store_file_and_bq_client():
    """stores=[StoreSpec(name='audit_log', backends=['memory','bigquery'])] must emit
    both the per-store file and the shared bigquery_rest_client.py.
    Both files must be valid Python.
    """
    base = load(FIXTURES_DIR / "full.yaml")
    config = base.model_copy(update={
        "stores": [StoreSpec(name="audit_log", backends=["memory", "bigquery"], default="memory")]
    })

    files = _render_dict(config)

    store_key = _store_key("audit_log")
    assert store_key in files, (
        f"Expected {store_key!r} in rendered output when store has bigquery backend"
    )
    assert _BQ_KEY in files, (
        f"Expected {_BQ_KEY!r} in rendered output when store has bigquery backend"
    )
    ast.parse(files[store_key])   # raises SyntaxError if rendered Python is invalid
    ast.parse(files[_BQ_KEY])     # raises SyntaxError if rendered Python is invalid


# ── Test 3 ────────────────────────────────────────────────────────────────────

def test_store_with_only_memory_backend_does_not_emit_bq_client():
    """stores=[StoreSpec(name='audit_log', backends=['memory'])] must emit the
    per-store file but NOT the bigquery_rest_client.py.
    """
    base = load(FIXTURES_DIR / "full.yaml")
    config = base.model_copy(update={
        "stores": [StoreSpec(name="audit_log", backends=["memory"], default="memory")]
    })

    files = _render_dict(config)

    store_key = _store_key("audit_log")
    assert store_key in files, (
        f"Expected {store_key!r} in rendered output when store has memory-only backend"
    )
    assert _BQ_KEY not in files, (
        f"Expected {_BQ_KEY!r} to be absent when no store has a bigquery backend"
    )
    ast.parse(files[store_key])  # raises SyntaxError if rendered Python is invalid


# ── Test 4 ────────────────────────────────────────────────────────────────────

def test_byte_identity_no_store_files_when_stores_empty():
    """Sanity / byte-identity guard: explicitly passing stores=[] produces the same
    result as loading full.yaml with no stores key — no store-related files appear.
    """
    base = load(FIXTURES_DIR / "full.yaml")
    config = base.model_copy(update={"stores": []})

    files = _render_dict(config)

    store_paths = [k for k in files if k.startswith("backend/services/") and k.endswith("_store.py")]
    assert store_paths == [], (
        f"Expected no *_store.py files when stores=[]; got: {store_paths}"
    )
    assert _BQ_KEY not in files, (
        f"Expected {_BQ_KEY!r} to be absent when stores=[]"
    )


# ── Test 5 ────────────────────────────────────────────────────────────────────

def test_pascal_and_snake_case_correctness_for_multi_word_store_name():
    """A store named 'user_profile' must produce the correct PascalCase and
    UPPER_SNAKE identifiers in the rendered file:

    - class UserProfileRecord
    - class UserProfileStore
    - class InMemoryUserProfileStore
    - def build_user_profile_store
    - USER_PROFILE_STORE_BACKEND  (env-var hint in docstring / factory)
    """
    base = load(FIXTURES_DIR / "full.yaml")
    config = base.model_copy(update={
        "stores": [StoreSpec(name="user_profile", backends=["memory"], default="memory")]
    })

    files = _render_dict(config)

    store_key = _store_key("user_profile")
    assert store_key in files, f"Expected {store_key!r} in rendered output"
    content = files[store_key]

    ast.parse(content)  # raises SyntaxError if rendered Python is invalid

    assert "class UserProfileRecord" in content, (
        "Expected 'class UserProfileRecord' in rendered user_profile_store.py"
    )
    assert "class UserProfileStore" in content, (
        "Expected 'class UserProfileStore' in rendered user_profile_store.py"
    )
    assert "class InMemoryUserProfileStore" in content, (
        "Expected 'class InMemoryUserProfileStore' in rendered user_profile_store.py"
    )
    assert "def build_user_profile_store" in content, (
        "Expected 'def build_user_profile_store' in rendered user_profile_store.py"
    )
    assert "USER_PROFILE_STORE_BACKEND" in content, (
        "Expected 'USER_PROFILE_STORE_BACKEND' env-var hint in rendered user_profile_store.py"
    )


# ── Test 6 ────────────────────────────────────────────────────────────────────

def test_storespec_default_must_be_in_backends():
    """Cross-field validator: default must be present in backends."""
    from agentforge.schema.models import StoreSpec
    from pydantic import ValidationError

    # Should raise — "bigquery" not in backends.
    raised = False
    try:
        StoreSpec(name="audit_log", backends=["memory"], default="bigquery")
    except ValidationError:
        raised = True
    assert raised, "Expected ValidationError when default not in backends"


# ── Test 7 ────────────────────────────────────────────────────────────────────

def test_storespec_name_rejects_invalid_identifiers():
    """name field uses SlugStr — rejects names with spaces, dashes, uppercase."""
    from agentforge.schema.models import StoreSpec
    from pydantic import ValidationError

    invalid_names = ["with spaces", "with-dashes", "AuditLog", "1starts_with_digit"]
    for name in invalid_names:
        raised = False
        try:
            StoreSpec(name=name, backends=["memory"], default="memory")
        except ValidationError:
            raised = True
        assert raised, f"Expected ValidationError for invalid name {name!r}"


# ── Test 8 ────────────────────────────────────────────────────────────────────

def test_postgres_only_store_emits_postgres_class():
    """Store with postgres in backends generates Postgres{Name}Store class."""
    base = load(FIXTURES_DIR / "full.yaml")
    store = StoreSpec(
        name="audit_log",
        backends=["memory", "postgres"],
        default="memory",
    )
    config = base.model_copy(update={"stores": [store]})

    files = _render_dict(config)

    assert "backend/services/audit_log_store.py" in files
    rendered = files["backend/services/audit_log_store.py"]
    ast.parse(rendered)
    assert "class PostgresAuditLogStore" in rendered
    assert "import asyncpg" in rendered


# ── Test 9 ────────────────────────────────────────────────────────────────────

def test_project_config_rejects_duplicate_store_names():
    """Duplicate store names raise ValidationError at ProjectConfig level."""
    base = load(FIXTURES_DIR / "full.yaml")
    s1 = StoreSpec(name="audit_log", backends=["memory"], default="memory")
    s2 = StoreSpec(name="audit_log", backends=["memory"], default="memory")
    raised = False
    try:
        base.model_copy(update={"stores": [s1, s2]})
    except Exception:
        raised = True
    if not raised:
        # Fall back to explicit re-validation if model_copy didn't trigger.
        from pydantic import ValidationError
        from agentforge.schema.models import ProjectConfig
        data = base.model_dump()
        data["stores"] = [s1.model_dump(), s2.model_dump()]
        raised = False
        try:
            ProjectConfig.model_validate(data)
        except ValidationError:
            raised = True
    assert raised, "Expected ValidationError on duplicate store names"
