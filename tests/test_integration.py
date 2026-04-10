"""End-to-end integration test: scaffold with all new flags enabled."""
import ast
import warnings
from pathlib import Path

import pytest

from agentforge.engine.renderer import TemplateRenderer
from agentforge.schema.loader import load

FIXTURE = Path(__file__).parent / "fixtures" / "all_flags_on.yaml"


def test_all_flags_on_integration():
    # Load the fixture — suppress any provider/model mismatch UserWarning
    # even though we use matched provider + model; this guards against
    # unrelated deprecation warnings polluting the test.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        cfg = load(FIXTURE)

    # Sanity: fixture carries the expected flag values.
    assert cfg.observability.structured_logging is True
    assert cfg.workflow.router_llm_provider == "anthropic"
    assert cfg.workflow.router_llm_model.value.startswith("claude-")
    assert cfg.enable_provider_registry is True

    r = TemplateRenderer()
    rendered = {str(p): c for p, c in r.render_all(cfg)}

    # Every generated .py file must parse as valid Python.
    for rel_path, content in rendered.items():
        if rel_path.endswith(".py"):
            try:
                ast.parse(content)
            except SyntaxError as e:
                pytest.fail(f"SyntaxError in {rel_path}: {e}")

    # ── structlog (Feature 1) ─────────────────────────────────────────
    logging_py = rendered["backend/observability/logging.py"]
    assert "import structlog" in logging_py, (
        "structlog template must be used when structured_logging=true"
    )
    middleware_py = rendered["backend/middleware/logging_middleware.py"]
    assert "clear_contextvars" in middleware_py, (
        "middleware must call clear_contextvars() when structlog is on"
    )
    # Project-level smoke test file must be generated.
    assert "backend/tests/test_structlog_setup.py" in rendered, (
        "structlog smoke test file must be generated when flag is on"
    )

    # ── Router vendor neutrality (Feature 2) ──────────────────────────
    router_py = rendered["backend/graph/nodes/query_router_node.py"]
    assert "from langchain_anthropic import ChatAnthropic" in router_py
    assert "ChatAnthropic(model_name=" in router_py
    assert "ChatOpenAI" not in router_py
    assert "langchain_openai" not in router_py

    requirements = rendered["requirements.txt"]
    assert "langchain-anthropic>=0.1.0" in requirements

    # ── Provider registry (Feature 3) ─────────────────────────────────
    assert "backend/config/provider_registry.py" in rendered
    assert "backend/config/providers.yaml" in rendered
    registry_py = rendered["backend/config/provider_registry.py"]
    assert "class ProviderRegistry" in registry_py
