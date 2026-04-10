"""Tests for enable_provider_registry flag — both branches of the renderer predicate."""
import ast
import re
from pathlib import Path

from agentforge.schema.loader import load
from agentforge.engine.renderer import TemplateRenderer

FIXTURES_DIR = Path(__file__).parent / "fixtures"

REGISTRY_PATH = "backend/config/provider_registry.py"
PROVIDERS_PATH = "backend/config/providers.yaml"


def _render_dict(config) -> dict[str, str]:
    return {str(path): content for path, content in TemplateRenderer().render_all(config)}


def test_provider_registry_off_by_default_omits_files():
    config = load(FIXTURES_DIR / "full.yaml")
    assert not config.enable_provider_registry, "full.yaml must have enable_provider_registry: false"

    files = _render_dict(config)

    assert REGISTRY_PATH not in files
    assert PROVIDERS_PATH not in files


def test_provider_registry_on_generates_both_files():
    base = load(FIXTURES_DIR / "full.yaml")
    config = base.model_copy(update={"enable_provider_registry": True})

    files = _render_dict(config)

    assert REGISTRY_PATH in files, f"Expected {REGISTRY_PATH!r} in rendered output"
    assert PROVIDERS_PATH in files, f"Expected {PROVIDERS_PATH!r} in rendered output"

    registry_py = files[REGISTRY_PATH]
    ast.parse(registry_py)  # raises SyntaxError if invalid Python
    assert "class ProviderRegistry" in registry_py

    providers_yaml = files[PROVIDERS_PATH]
    assert providers_yaml.strip(), "providers.yaml must not be empty"
    assert "providers" in providers_yaml


def test_provider_registry_content_has_no_domain_leakage():
    base = load(FIXTURES_DIR / "full.yaml")
    config = base.model_copy(update={"enable_provider_registry": True})

    files = _render_dict(config)
    registry_py = files[REGISTRY_PATH]

    forbidden_patterns = [
        r"facebook",
        r"google",
        r"\bads\b",
        r"campaign",
        r"gads",
        r"fbads",
    ]
    for pattern in forbidden_patterns:
        assert not re.search(pattern, registry_py, re.IGNORECASE), (
            f"Domain leakage: pattern {pattern!r} found in {REGISTRY_PATH}"
        )
