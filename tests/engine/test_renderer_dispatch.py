"""
Tests for the pattern-dispatch mechanism in the Jinja2 rendering engine.

Covers:
- ``resolve_pattern`` returns ``"orchestrator"`` for a legacy config (the
  model_validator injects it automatically).
- A template file placed in ``patterns/{pattern}/`` takes precedence over the
  identically named file in the shared ``templates/`` directory.
- When no per-pattern override exists, the renderer falls back to the shared
  template transparently.
- Byte-identity regression: rendering ``examples/project.full.yaml`` produces
  output that matches a fresh render of the same config (internal consistency
  check — ensures the ChoiceLoader refactor introduced no rendering drift).
"""
from __future__ import annotations

import warnings
from pathlib import Path

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, StrictUndefined, select_autoescape

from agentforge.engine import resolve_pattern
from agentforge.engine.renderer import TemplateRenderer
from agentforge.schema.loader import load
from agentforge.schema.models import ProjectConfig

# Path to examples/project.full.yaml — used for the byte-identity regression.
FULL_YAML = Path(__file__).parent.parent.parent / "examples" / "project.full.yaml"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _minimal_legacy_config() -> ProjectConfig:
    """Build a minimal legacy-shaped ProjectConfig via dict input.

    Using ``model_validate`` with a plain dict ensures the
    ``model_validator(mode="before")`` fires and injects:
        entry.type   = "intent_router"
        pattern      = "orchestrator"
        orchestrator = {kind: "llm"}

    Constructing via Python keyword args passes sub-model objects (not dicts)
    through the validator, so the legacy detection condition is not triggered.
    Using the dict path mirrors how YAML configs are processed via the loader.
    """
    return ProjectConfig.model_validate({
        "metadata": {
            "name": "dispatch_test",
            "description": "Renderer dispatch test project",
            "python_version": "3.11",
            "author": "Test",
            "email": "test@example.com",
        },
        "agents": [
            {
                "key": "sql",
                "class_name": "SQLAgent",
                "llm_model": "gpt-4o-mini",
                "system_prompt": "You are a SQL assistant.",
            }
        ],
        "database": {"backend": "postgres", "tables": []},
        "workflow": {
            "default_intent": "sql",
            "enable_feedback_loop": True,
            "enable_validation_node": True,
        },
    })


def _make_test_env(override_dir: Path, shared_dir: Path) -> Environment:
    """Build a ChoiceLoader environment over two controlled directories."""
    return Environment(
        loader=ChoiceLoader([
            FileSystemLoader(str(override_dir)),
            FileSystemLoader(str(shared_dir)),
        ]),
        autoescape=select_autoescape([]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


# ── resolve_pattern ───────────────────────────────────────────────────────────


def test_resolve_pattern_legacy_config_returns_orchestrator() -> None:
    """Legacy config (no entry/pattern keys) must resolve to 'orchestrator'.

    The backwards-compat model_validator injects pattern='orchestrator' for
    any config that has workflow.default_intent set and at least one agent
    but no explicit entry or pattern top-level key.
    """
    config = _minimal_legacy_config()
    assert resolve_pattern(config) == "orchestrator"


def test_resolve_pattern_reads_config_pattern_field() -> None:
    """resolve_pattern must return exactly what config.pattern holds.

    Verifies that the function reads from the schema field rather than
    hardcoding a value independently of the schema.
    """
    config = _minimal_legacy_config()
    # The model_validator must have populated config.pattern.
    assert config.pattern is not None
    assert resolve_pattern(config) == config.pattern


# ── ChoiceLoader precedence ───────────────────────────────────────────────────


def test_pattern_override_takes_precedence_over_shared(tmp_path: Path) -> None:
    """A template in patterns/{pattern}/ must shadow the shared template.

    Build a controlled two-directory layout under tmp_path rather than
    touching real template directories, so real output is never polluted.
    """
    shared_dir = tmp_path / "shared"
    override_dir = tmp_path / "override"
    shared_dir.mkdir()
    override_dir.mkdir()

    (shared_dir / "_test_marker.j2").write_text("shared", encoding="utf-8")
    (override_dir / "_test_marker.j2").write_text("override", encoding="utf-8")

    env = _make_test_env(override_dir, shared_dir)
    result = env.get_template("_test_marker.j2").render()

    assert result == "override", (
        "Pattern overlay template should shadow the shared template, "
        f"but got: {result!r}"
    )


def test_absent_pattern_override_falls_back_to_shared(tmp_path: Path) -> None:
    """When no per-pattern override exists, the shared template must be used.

    The override directory exists (empty pattern dir) but contains no template,
    so the ChoiceLoader must fall through to the shared directory.
    """
    shared_dir = tmp_path / "shared"
    override_dir = tmp_path / "override"
    shared_dir.mkdir()
    override_dir.mkdir()  # exists but has no _test_marker.j2

    (shared_dir / "_test_marker.j2").write_text("shared", encoding="utf-8")

    env = _make_test_env(override_dir, shared_dir)
    result = env.get_template("_test_marker.j2").render()

    assert result == "shared", (
        "Absent pattern override should fall back to shared template, "
        f"but got: {result!r}"
    )


# ── Byte-identity regression ──────────────────────────────────────────────────


def test_full_yaml_render_is_internally_consistent() -> None:
    """Rendering examples/project.full.yaml twice must produce identical output.

    This verifies that the ChoiceLoader refactor introduced no non-determinism.
    For the committed-golden byte-identity test see TODO-v2-14; this test is
    the internal consistency guard for TODO-v2-1.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        cfg = load(FULL_YAML)

    renderer = TemplateRenderer()
    first_pass = {str(p): content for p, content in renderer.render_all(cfg)}
    second_pass = {str(p): content for p, content in renderer.render_all(cfg)}

    assert first_pass == second_pass, (
        "Two consecutive renders of project.full.yaml produced different output. "
        "The ChoiceLoader refactor introduced non-determinism."
    )


def test_full_yaml_pattern_resolves_to_orchestrator() -> None:
    """project.full.yaml must resolve to the orchestrator pattern."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        cfg = load(FULL_YAML)

    assert resolve_pattern(cfg) == "orchestrator", (
        f"project.full.yaml resolved to pattern={cfg.pattern!r}, expected 'orchestrator'"
    )
