"""Tests for security.enable_prompt_secret_scan — conditional emission of
backend/security/prompt_secret_scanner.py."""
import ast
from pathlib import Path

from agentforge.schema.loader import load
from agentforge.engine.renderer import TemplateRenderer

FIXTURES_DIR = Path(__file__).parent / "fixtures"

_SCANNER_KEY = "backend/security/prompt_secret_scanner.py"


def _render_dict(config) -> dict[str, str]:
    """Return render_all output as a dict keyed by str(path)."""
    return {str(path): content for path, content in TemplateRenderer().render_all(config)}


def test_prompt_secret_scanner_emitted_when_flag_on():
    """enable_prompt_secret_scan=True must render prompt_secret_scanner.py as valid Python."""
    base = load(FIXTURES_DIR / "full.yaml")
    new_sec = base.security.model_copy(update={"enable_prompt_secret_scan": True})
    config = base.model_copy(update={"security": new_sec})

    files = _render_dict(config)

    assert _SCANNER_KEY in files, (
        f"Expected {_SCANNER_KEY!r} in rendered output when enable_prompt_secret_scan=True"
    )
    ast.parse(files[_SCANNER_KEY])  # raises SyntaxError if the rendered file is invalid Python


def test_prompt_secret_scanner_not_emitted_when_flag_off():
    """enable_prompt_secret_scan=False (default) must NOT render prompt_secret_scanner.py."""
    config = load(FIXTURES_DIR / "full.yaml")

    files = _render_dict(config)

    assert _SCANNER_KEY not in files, (
        f"Expected {_SCANNER_KEY!r} to be absent from rendered output when enable_prompt_secret_scan=False"
    )


def test_prompt_secret_scanner_contains_expected_symbols():
    """When the flag is on, the rendered file must define SecretLeakError and scan_prompt_for_secrets."""
    base = load(FIXTURES_DIR / "full.yaml")
    new_sec = base.security.model_copy(update={"enable_prompt_secret_scan": True})
    config = base.model_copy(update={"security": new_sec})

    files = _render_dict(config)
    scanner_py = files[_SCANNER_KEY]

    assert "class SecretLeakError" in scanner_py
    assert "def scan_prompt_for_secrets" in scanner_py
