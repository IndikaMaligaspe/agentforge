"""
Tests for the pre-commit hooks scaffold template rendering.

Verifies predicate gating, YAML validity, expected hook presence,
and optional pre-commit CLI schema validation.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

from agentforge.engine.renderer import TemplateRenderer
from agentforge.schema.models import (
    AgentConfig, LLMModel, ProjectConfig, ProjectMetadata,
    DatabaseConfig, WorkflowConfig, APIConfig, ObservabilityConfig,
    SecurityConfig, CiConfig, DevelopmentConfig,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_config(pre_commit: bool) -> ProjectConfig:
    return ProjectConfig(
        metadata=ProjectMetadata(
            name="test_proj",
            description="Test project",
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
        database=DatabaseConfig(backend="postgres"),  # type: ignore[call-arg]
        api=APIConfig(title="Test API"),  # type: ignore[call-arg]
        observability=ObservabilityConfig(enable_tracing=False),  # type: ignore[call-arg]
        security=SecurityConfig(enable_auth=False),  # type: ignore[call-arg]
        ci=CiConfig(),  # type: ignore[call-arg]
        development=DevelopmentConfig(pre_commit=pre_commit),  # type: ignore[call-arg]
        enable_provider_registry=False,
    )


def _render_files(config: ProjectConfig) -> dict[str, str]:
    renderer = TemplateRenderer()
    return {str(path): content for path, content in renderer.render_all(config)}


def _precommit_binary_usable() -> bool:
    """Return True only if the pre-commit binary exists and actually executes."""
    binary = shutil.which("pre-commit")
    if binary is None:
        return False
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


# ── Predicate tests ───────────────────────────────────────────────────────────

def test_precommit_file_not_rendered_when_flag_false():
    """File must be absent when development.pre_commit=False (default)."""
    files = _render_files(_make_config(pre_commit=False))
    assert ".pre-commit-config.yaml" not in files


def test_precommit_file_rendered_when_flag_true():
    """File must be present when development.pre_commit=True."""
    files = _render_files(_make_config(pre_commit=True))
    assert ".pre-commit-config.yaml" in files


# ── YAML validity tests ───────────────────────────────────────────────────────

def test_precommit_yaml_parses():
    """Rendered content must be parseable by yaml.safe_load."""
    files = _render_files(_make_config(pre_commit=True))
    content = files[".pre-commit-config.yaml"]
    parsed = yaml.safe_load(content)
    assert parsed is not None


def test_precommit_yaml_has_repos_top_level_list():
    """Parsed YAML must have a top-level 'repos' key that is a list."""
    files = _render_files(_make_config(pre_commit=True))
    parsed = yaml.safe_load(files[".pre-commit-config.yaml"])
    assert "repos" in parsed
    assert isinstance(parsed["repos"], list)
    assert len(parsed["repos"]) > 0


# ── Hook content tests ────────────────────────────────────────────────────────

def test_precommit_contains_ruff_hook():
    """Rendered YAML must include a ruff hook entry."""
    files = _render_files(_make_config(pre_commit=True))
    parsed = yaml.safe_load(files[".pre-commit-config.yaml"])

    all_hook_ids = [
        hook["id"]
        for repo in parsed["repos"]
        for hook in repo.get("hooks", [])
    ]
    assert "ruff" in all_hook_ids


def test_precommit_contains_ruff_format_hook():
    """Rendered YAML must include a ruff-format hook entry."""
    files = _render_files(_make_config(pre_commit=True))
    parsed = yaml.safe_load(files[".pre-commit-config.yaml"])

    all_hook_ids = [
        hook["id"]
        for repo in parsed["repos"]
        for hook in repo.get("hooks", [])
    ]
    assert "ruff-format" in all_hook_ids


def test_precommit_contains_pre_commit_hooks():
    """Rendered YAML must include trailing-whitespace, end-of-file-fixer, check-yaml, check-toml."""
    files = _render_files(_make_config(pre_commit=True))
    parsed = yaml.safe_load(files[".pre-commit-config.yaml"])

    all_hook_ids = {
        hook["id"]
        for repo in parsed["repos"]
        for hook in repo.get("hooks", [])
    }
    for expected in ("trailing-whitespace", "end-of-file-fixer", "check-yaml", "check-toml"):
        assert expected in all_hook_ids, f"Expected hook '{expected}' not found"


# ── Optional: pre-commit CLI validation ──────────────────────────────────────

@pytest.mark.skipif(
    not _precommit_binary_usable(),
    reason="pre-commit binary not available or not executable",
)
def test_precommit_validate_config_passes():
    """If pre-commit binary is available and usable, validate-config must exit 0."""
    files = _render_files(_make_config(pre_commit=True))
    content = files[".pre-commit-config.yaml"]

    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / ".pre-commit-config.yaml"
        config_path.write_text(content)

        result = subprocess.run(
            ["pre-commit", "validate-config", str(config_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"pre-commit validate-config failed:\n{result.stdout}\n{result.stderr}"
        )
