"""
Tests for Makefile template rendering (TODO-5).

Covers:
- Minimal config (defaults): always-on targets present; conditional targets absent.
- database.use_alembic=True: db-up, db-migrate, db-revision targets present.
- testing.enable_benchmarks=True + eval_framework=deepeval: test-benchmarks present.
- Recipe lines use real TAB characters (not spaces).
- help target contains the expected grep/awk one-liner.
- Multiple feature flags simultaneously renders all relevant targets.
- Optional GNU Make dry-run: make -n -f <rendered> help (skipped if make not on PATH).
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

import pytest

from agentforge.engine.renderer import TemplateRenderer
from agentforge.schema.models import (
    AgentConfig,
    DatabaseConfig,
    DBBackend,
    LLMModel,
    ProjectConfig,
    ProjectMetadata,
    TestingConfig,
    WorkflowConfig,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_config(
    use_alembic: bool = False,
    db_backend: str = "postgres",
    enable_benchmarks: bool = False,
    eval_framework: Literal["none", "deepeval"] = "none",
) -> ProjectConfig:
    """Build a minimal valid ProjectConfig for Makefile rendering tests."""
    testing = TestingConfig(  # type: ignore[call-arg]
        enable_benchmarks=enable_benchmarks,
        eval_framework=eval_framework,
    )

    return ProjectConfig(
        metadata=ProjectMetadata(
            name="test_project",
            description="Makefile render test",
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
        database=DatabaseConfig(
            backend=DBBackend(db_backend),
            connection_env_var="DATABASE_URL",
            pool_size=5,
            max_overflow=10,
            use_alembic=use_alembic,
        ),
        workflow=WorkflowConfig(default_intent="sql"),  # type: ignore[call-arg]
        testing=testing,
        enable_provider_registry=False,
    )


def _render_makefile(config: ProjectConfig) -> str:
    """Render all templates and return the Makefile content."""
    renderer = TemplateRenderer()
    rendered = {str(path): content for path, content in renderer.render_all(config)}
    assert "Makefile" in rendered, "Makefile must always be rendered"
    return rendered["Makefile"]


# ── Makefile always present ───────────────────────────────────────────────────

def test_makefile_always_rendered():
    """Makefile must appear in render_all output regardless of feature flags."""
    config = _make_config()
    renderer = TemplateRenderer()
    paths = [str(p) for p, _ in renderer.render_all(config)]
    assert "Makefile" in paths


# ── Always-on targets ─────────────────────────────────────────────────────────

ALWAYS_ON_TARGETS = ["help", "install", "run", "test", "lint", "format", "clean"]


@pytest.mark.parametrize("target", ALWAYS_ON_TARGETS)
def test_always_on_target_present_with_minimal_config(target: str):
    """Each always-on target must appear in the Makefile with default settings."""
    content = _render_makefile(_make_config())
    assert f"{target}:" in content, f"Expected target '{target}:' in Makefile"


# ── Conditional targets absent with minimal config ────────────────────────────

CONDITIONAL_TARGETS = ["db-up", "db-down", "db-migrate", "db-revision", "test-benchmarks"]


@pytest.mark.parametrize("target", CONDITIONAL_TARGETS)
def test_conditional_target_absent_with_minimal_config(target: str):
    """Conditional targets must NOT appear in the Makefile with default settings."""
    content = _render_makefile(_make_config())
    assert f"{target}:" not in content, (
        f"Target '{target}:' must be absent when its feature is disabled"
    )


# ── Alembic targets ───────────────────────────────────────────────────────────

def test_alembic_targets_present_when_use_alembic_true():
    """db-up, db-down, db-migrate, db-revision must appear when use_alembic=True."""
    content = _render_makefile(_make_config(use_alembic=True, db_backend="postgres"))
    for target in ["db-up:", "db-down:", "db-migrate:", "db-revision:"]:
        assert target in content, f"Expected '{target}' when use_alembic=True"


def test_alembic_targets_absent_when_use_alembic_false():
    """Alembic targets must NOT appear when use_alembic=False."""
    content = _render_makefile(_make_config(use_alembic=False))
    for target in ["db-up:", "db-down:", "db-migrate:", "db-revision:"]:
        assert target not in content, f"Unexpected '{target}' when use_alembic=False"


# ── Benchmark target ──────────────────────────────────────────────────────────

def test_benchmark_target_present_when_enabled():
    """test-benchmarks must appear when enable_benchmarks=True and eval_framework=deepeval."""
    content = _render_makefile(
        _make_config(enable_benchmarks=True, eval_framework="deepeval")
    )
    assert "test-benchmarks:" in content


def test_benchmark_target_absent_when_benchmarks_disabled():
    """test-benchmarks must NOT appear when benchmarks are not enabled."""
    content = _render_makefile(_make_config())
    assert "test-benchmarks:" not in content


# ── Tab indentation (Make requirement) ────────────────────────────────────────

def test_recipe_tab_byte_check():
    """Byte-level assertion: the help recipe line must start with byte 0x09 (TAB)."""
    content = _render_makefile(_make_config())
    content_bytes = content.encode("utf-8")
    lines = content_bytes.split(b"\n")
    help_recipe = [ln for ln in lines if ln.startswith(b"\t@grep")]
    assert len(help_recipe) == 1, "Expected exactly one help recipe line starting with TAB+@grep"
    assert help_recipe[0][0:1] == b"\x09", "help recipe must start with TAB byte (0x09)"


# ── help target grep/awk one-liner ────────────────────────────────────────────

def test_help_target_contains_grep_awk_recipe():
    """help target must use the standard grep/awk one-liner for target discovery."""
    content = _render_makefile(_make_config())
    assert "@grep -E" in content
    assert "awk" in content
    assert "MAKEFILE_LIST" in content


def test_help_target_pattern_matches_double_hash():
    """grep pattern must match the '## comment' convention used by all targets."""
    content = _render_makefile(_make_config())
    # The grep expression must look for '## ' style comments
    assert "## " in content or "##" in content


# ── No mutual-exclusivity bugs ────────────────────────────────────────────────

def test_all_feature_flags_simultaneously():
    """Enabling all optional features must render all conditional targets together."""
    content = _render_makefile(
        _make_config(
            use_alembic=True,
            db_backend="postgres",
            enable_benchmarks=True,
            eval_framework="deepeval",
        )
    )
    # Always-on targets still present
    for target in ALWAYS_ON_TARGETS:
        assert f"{target}:" in content, f"Always-on target '{target}:' missing"
    # All conditional targets present
    for target in ["db-up:", "db-down:", "db-migrate:", "db-revision:", "test-benchmarks:"]:
        assert target in content, f"Conditional target '{target}' missing"


# ── GNU Make dry-run ──────────────────────────────────────────────────────────

@pytest.mark.skipif(shutil.which("make") is None, reason="make binary not on PATH")
def test_gnu_make_dry_run_help():
    """Rendered Makefile must parse without error under GNU Make dry-run."""
    content = _render_makefile(_make_config())
    with tempfile.NamedTemporaryFile(
        mode="w", suffix="Makefile", delete=False, prefix="agentforge_test_"
    ) as f:
        f.write(content)
        tmp_path = f.name

    try:
        result = subprocess.run(
            ["make", "-n", "-f", tmp_path, "help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, (
            f"make -n -f <rendered> help failed with exit code {result.returncode}\n"
            f"stderr: {result.stderr}"
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)
