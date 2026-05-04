"""Tests for development.type_checking — conditional emission of pyrightconfig.json."""
import json
from pathlib import Path

from agentforge.schema.loader import load
from agentforge.engine.renderer import TemplateRenderer

FIXTURES_DIR = Path(__file__).parent / "fixtures"

_PYRIGHT_KEY = "pyrightconfig.json"


def _render_dict(config) -> dict[str, str]:
    """Return render_all output as a dict keyed by str(path)."""
    return {str(path): content for path, content in TemplateRenderer().render_all(config)}


def test_pyrightconfig_emitted_when_type_checking_pyright():
    """type_checking='pyright' must render pyrightconfig.json as valid JSON."""
    base = load(FIXTURES_DIR / "full.yaml")
    new_dev = base.development.model_copy(update={"type_checking": "pyright"})
    config = base.model_copy(update={"development": new_dev})

    files = _render_dict(config)

    assert _PYRIGHT_KEY in files, (
        f"Expected {_PYRIGHT_KEY!r} in rendered output when type_checking='pyright'"
    )
    json.loads(files[_PYRIGHT_KEY])  # raises JSONDecodeError if the rendered file is invalid JSON


def test_pyrightconfig_not_emitted_when_type_checking_none():
    """type_checking='none' (default) must NOT render pyrightconfig.json."""
    config = load(FIXTURES_DIR / "full.yaml")

    files = _render_dict(config)

    assert _PYRIGHT_KEY not in files, (
        f"Expected {_PYRIGHT_KEY!r} to be absent from rendered output when type_checking='none'"
    )


def test_pyrightconfig_contains_expected_keys():
    """When emitted, the parsed JSON must contain all expected pyright config keys."""
    base = load(FIXTURES_DIR / "full.yaml")
    new_dev = base.development.model_copy(update={"type_checking": "pyright"})
    config = base.model_copy(update={"development": new_dev})

    files = _render_dict(config)
    parsed = json.loads(files[_PYRIGHT_KEY])

    expected_keys = {
        "venvPath",
        "venv",
        "pythonVersion",
        "extraPaths",
        "reportMissingImports",
        "reportMissingTypeStubs",
    }
    missing = expected_keys - set(parsed.keys())
    assert not missing, (
        f"pyrightconfig.json is missing expected keys: {sorted(missing)}"
    )
