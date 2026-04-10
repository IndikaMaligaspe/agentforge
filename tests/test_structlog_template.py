"""Tests for structured_logging flag — both branches of the renderer swap."""
import ast
from pathlib import Path

from agentforge.schema.loader import load
from agentforge.engine.renderer import TemplateRenderer

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _render_dict(config) -> dict[str, str]:
    """Return render_all output as a dict keyed by str(path)."""
    return {str(path): content for path, content in TemplateRenderer().render_all(config)}


def test_structured_logging_on_renders_structlog_template():
    """structured_logging=True must select logging_structlog.py.j2."""
    base = load(FIXTURES_DIR / "full.yaml")
    new_obs = base.observability.model_copy(update={"structured_logging": True})
    config = base.model_copy(update={"observability": new_obs})

    files = _render_dict(config)
    logging_py = files["backend/observability/logging.py"]

    assert "import structlog" in logging_py
    assert "from logging.handlers import RotatingFileHandler" not in logging_py
    ast.parse(logging_py)  # raises SyntaxError if invalid
    assert "structlog>=24.1.0" in files["requirements.txt"]

    # Middleware assertions: structlog branch must use clear_contextvars
    middleware_py = files["backend/middleware/logging_middleware.py"]
    assert "from structlog.contextvars import clear_contextvars" in middleware_py
    assert "clear_contextvars()" in middleware_py
    assert '"request_started"' in middleware_py
    assert '"request_completed"' in middleware_py
    assert '"request_failed"' in middleware_py
    ast.parse(middleware_py)  # raises SyntaxError if invalid

    # Test smoke file assertions: must be present when structured_logging=True
    test_file_key = "backend/tests/test_structlog_setup.py"
    assert test_file_key in files, (
        f"Expected {test_file_key!r} in rendered output when structured_logging=True"
    )
    test_py = files[test_file_key]
    assert "import structlog" in test_py
    ast.parse(test_py)  # raises SyntaxError if invalid


def test_structured_logging_off_renders_stdlib_template():
    """structured_logging=False (default) must select logging.py.j2."""
    config = load(FIXTURES_DIR / "full.yaml")

    files = _render_dict(config)
    logging_py = files["backend/observability/logging.py"]

    assert "import structlog" not in logging_py
    assert "JsonFormatter" in logging_py
    ast.parse(logging_py)  # raises SyntaxError if invalid
    assert "structlog>=24.1.0" in files["requirements.txt"]

    # Middleware assertions: stdlib branch must NOT use clear_contextvars
    middleware_py = files["backend/middleware/logging_middleware.py"]
    assert "clear_contextvars" not in middleware_py
    assert 'extra={' in middleware_py
    assert '"props"' in middleware_py
    assert "Request started:" in middleware_py
    ast.parse(middleware_py)  # raises SyntaxError if invalid

    # Test smoke file assertions: must NOT be present when structured_logging=False
    test_file_key = "backend/tests/test_structlog_setup.py"
    assert test_file_key not in files, (
        f"Expected {test_file_key!r} to be absent from rendered output when structured_logging=False"
    )
