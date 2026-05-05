"""Tests for the per-store backend field in settings.py.j2.

Verifies that when StoreSpec entries are declared, the rendered
backend/config/settings.py contains a `<name>_store_backend: str`
field for each store, with the StoreSpec's default as the field default.
"""
import ast
from pathlib import Path

from agentforge.schema.loader import load
from agentforge.schema.models import StoreSpec
from agentforge.engine.renderer import TemplateRenderer

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _render_dict(config) -> dict[str, str]:
    renderer = TemplateRenderer()
    files = renderer.render_all(config)
    return {str(path): content for path, content in files}


def test_settings_emitted_when_stores_declared():
    """Settings.py is emitted when at least one store is declared, even
    without enable_settings_module or multi_tenancy.enabled."""
    base = load(FIXTURES_DIR / "full.yaml")
    store = StoreSpec(name="audit_log", backends=["memory"], default="memory")
    config = base.model_copy(update={"stores": [store]})

    files = _render_dict(config)
    assert "backend/config/settings.py" in files
    rendered = files["backend/config/settings.py"]
    ast.parse(rendered)


def test_per_store_backend_field_present():
    """A `<name>_store_backend: str` field is emitted for each store, with
    the StoreSpec's default as the field default."""
    base = load(FIXTURES_DIR / "full.yaml")
    s1 = StoreSpec(name="audit_log", backends=["memory", "bigquery"], default="bigquery")
    s2 = StoreSpec(name="cache", backends=["memory"], default="memory")
    config = base.model_copy(update={"stores": [s1, s2]})

    files = _render_dict(config)
    rendered = files["backend/config/settings.py"]

    assert 'audit_log_store_backend: str = Field(default="bigquery")' in rendered
    assert 'cache_store_backend: str = Field(default="memory")' in rendered
    ast.parse(rendered)


def test_no_store_section_when_stores_empty():
    """With stores=[] (default), no per-store fields appear in settings.py
    even when the file IS emitted via enable_settings_module."""
    base = load(FIXTURES_DIR / "full.yaml")
    config = base.model_copy(update={"enable_settings_module": True})

    files = _render_dict(config)
    assert "backend/config/settings.py" in files
    rendered = files["backend/config/settings.py"]

    assert "_store_backend" not in rendered
    assert "Store backend selection" not in rendered
    ast.parse(rendered)
