"""
Tests for GitHub Actions CI scaffold rendering (TODO-2).

Covers:
- File NOT rendered when provider == "none" (default).
- File rendered when provider == "github".
- Install step content differs per installer (uv/pip/poetry).
- Rendered YAML is parseable by yaml.safe_load.
- No hardcoded "uv" string outside the parameterized install block.
"""
import re
import yaml
import pytest

from agentforge.schema.models import (
    AgentConfig,
    CiConfig,
    LLMModel,
    ProjectConfig,
    ProjectMetadata,
    WorkflowConfig,
)
from agentforge.engine.renderer import TemplateRenderer


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_config(provider: str = "none", installer: str = "uv", ci_python: str = "3.12") -> ProjectConfig:
    """Build a minimal valid ProjectConfig with the given CI settings."""
    return ProjectConfig(
        metadata=ProjectMetadata(
            name="test_project",
            description="CI render test",
            python_version="3.11",
            author="Test Author",
            email="test@example.com",
        ),
        agents=[
            AgentConfig(
                key="sql",
                class_name="SqlAgent",
                llm_model=LLMModel.GPT4O_MINI,
                system_prompt="You are a helpful assistant.",
                needs_validation=False,
            )
        ],
        workflow=WorkflowConfig(default_intent="sql"),  # type: ignore[call-arg]
        ci=CiConfig(provider=provider, installer=installer, python_version=ci_python),  # type: ignore[call-arg]
        enable_provider_registry=False,
    )


def _render_map(config: ProjectConfig) -> dict[str, str]:
    """Render all templates and return a {relative_path: content} mapping."""
    renderer = TemplateRenderer()
    return {str(path): content for path, content in renderer.render_all(config)}


CI_OUTPUT_PATH = ".github/workflows/ci.yml"


# ── Schema defaults ───────────────────────────────────────────────────────────

def test_ci_config_defaults():
    """CiConfig must default to provider=none, python_version=3.12, installer=uv."""
    ci = CiConfig()
    assert ci.provider == "none"
    assert ci.python_version == "3.12"
    assert ci.installer == "uv"


def test_project_config_ci_defaults_to_none():
    """ProjectConfig.ci.provider must default to none so existing projects are unaffected."""
    config = _make_config()
    assert config.ci.provider == "none"


# ── File presence predicate ───────────────────────────────────────────────────

def test_ci_file_absent_when_provider_none():
    """No CI file must be emitted when ci.provider is 'none'."""
    rendered = _render_map(_make_config(provider="none"))
    assert CI_OUTPUT_PATH not in rendered


def test_ci_file_present_when_provider_github():
    """CI file must be emitted at .github/workflows/ci.yml when ci.provider is 'github'."""
    rendered = _render_map(_make_config(provider="github"))
    assert CI_OUTPUT_PATH in rendered


# ── YAML parseability ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("installer", ["uv", "pip", "poetry"])
def test_rendered_yaml_is_parseable(installer: str):
    """Rendered CI YAML must be parseable by yaml.safe_load for all installers."""
    rendered = _render_map(_make_config(provider="github", installer=installer))
    content = rendered[CI_OUTPUT_PATH]
    parsed = yaml.safe_load(content)
    assert isinstance(parsed, dict)
    assert "jobs" in parsed
    # yaml.safe_load converts the bare `on:` key to boolean True per YAML 1.1 spec
    assert True in parsed


# ── Python version parameterization ──────────────────────────────────────────

def test_ci_python_version_in_rendered_output():
    """The ci.python_version must appear in the rendered workflow matrix."""
    rendered = _render_map(_make_config(provider="github", ci_python="3.13"))
    content = rendered[CI_OUTPUT_PATH]
    assert "3.13" in content


# ── Install step per installer ────────────────────────────────────────────────

def test_uv_install_step_uses_uv_sync():
    """uv installer must render 'uv sync' in the install dependencies step."""
    rendered = _render_map(_make_config(provider="github", installer="uv"))
    content = rendered[CI_OUTPUT_PATH]
    assert "uv sync" in content


def test_pip_install_step_uses_pip_install():
    """pip installer must render 'pip install' in the install dependencies step."""
    rendered = _render_map(_make_config(provider="github", installer="pip"))
    content = rendered[CI_OUTPUT_PATH]
    assert "pip install" in content


def test_poetry_install_step_uses_poetry_install():
    """poetry installer must render 'poetry install' in the install dependencies step."""
    rendered = _render_map(_make_config(provider="github", installer="poetry"))
    content = rendered[CI_OUTPUT_PATH]
    assert "poetry install" in content


# ── Install steps are mutually exclusive ─────────────────────────────────────

def test_pip_installer_has_no_uv_commands():
    """pip installer output must not contain uv-specific commands."""
    rendered = _render_map(_make_config(provider="github", installer="pip"))
    content = rendered[CI_OUTPUT_PATH]
    # uv sync and uv run are uv-specific; they must not appear in pip mode
    assert "uv sync" not in content
    assert "uv run" not in content


def test_poetry_installer_has_no_uv_commands():
    """poetry installer output must not contain uv-specific commands."""
    rendered = _render_map(_make_config(provider="github", installer="poetry"))
    content = rendered[CI_OUTPUT_PATH]
    assert "uv sync" not in content
    assert "uv run" not in content


def test_uv_installer_has_no_pip_install_command():
    """uv installer output must not contain bare 'pip install'."""
    rendered = _render_map(_make_config(provider="github", installer="uv"))
    content = rendered[CI_OUTPUT_PATH]
    assert "pip install" not in content


# ── No hardcoded "uv" outside the parameterized install block ─────────────────

def test_pip_output_has_no_uv_string():
    """The string 'uv' must not appear anywhere in pip-mode output."""
    rendered = _render_map(_make_config(provider="github", installer="pip"))
    content = rendered[CI_OUTPUT_PATH]
    assert "uv" not in content


def test_poetry_output_has_no_uv_string():
    """The string 'uv' must not appear anywhere in poetry-mode output."""
    rendered = _render_map(_make_config(provider="github", installer="poetry"))
    content = rendered[CI_OUTPUT_PATH]
    assert "uv" not in content


# ── Lint and test steps always present ───────────────────────────────────────

@pytest.mark.parametrize("installer", ["uv", "pip", "poetry"])
def test_ruff_lint_step_present(installer: str):
    """ruff lint step must be present for all installers."""
    rendered = _render_map(_make_config(provider="github", installer=installer))
    content = rendered[CI_OUTPUT_PATH]
    assert "ruff check" in content


@pytest.mark.parametrize("installer", ["uv", "pip", "poetry"])
def test_pytest_step_present(installer: str):
    """pytest step must be present for all installers."""
    rendered = _render_map(_make_config(provider="github", installer=installer))
    content = rendered[CI_OUTPUT_PATH]
    assert "pytest" in content


# ── Branch trigger — no Madgicx-specific branch names ────────────────────────

def test_branch_triggers_use_main_not_master_or_dev():
    """Workflow push trigger must use 'main' only; must not list 'master' or 'dev' as branches."""
    rendered = _render_map(_make_config(provider="github", installer="uv"))
    content = rendered[CI_OUTPUT_PATH]
    parsed = yaml.safe_load(content)
    # The `on` key parses as boolean True in YAML 1.1
    trigger = parsed[True]
    push_branches = trigger.get("push", {}).get("branches", [])
    assert "main" in push_branches
    assert "master" not in push_branches
    assert "dev" not in push_branches
