"""
TODO-v2-14: Non-negotiable byte-identity regression bookend.

This test is the final shippability gate for v2. Every YAML listed in
V1_FIXTURES is a legacy-path config that must render without using any
v2-specific overlays (no passthrough/direct entry nodes, no react/workflow/
fanout/planner pattern templates). The golden tree captures the end-of-v2
renderer output for each such fixture; v1-equivalence is validated by the
independent structural assertions in tests/e2e/test_full_scaffold.py
(EXPECTED_FILES list) which assert the legacy-compat shape directly.
Rendering MUST produce output byte-identical to the committed golden tree at:

    tests/fixtures/snapshots/<fixture_name>/

If this test fails, v2 broke backwards compatibility and is NOT shippable.

Rules:
- This test MUST NEVER be skipped.
- This test MUST NEVER auto-update the golden tree.
- To update the golden tree, the developer must do so manually or via
  the authoring surface (test_scaffold_snapshot.py with UPDATE_SNAPSHOTS=1).
  This test is the gate, not the authoring surface.
"""
from pathlib import Path

import pytest

from agentforge.schema.loader import load
from agentforge.engine.renderer import TemplateRenderer

# ---------------------------------------------------------------------------
# Root anchors — derived from a single constant so path duplication is zero.
# ---------------------------------------------------------------------------
_TESTS_DIR = Path(__file__).parent
_REPO_ROOT = _TESTS_DIR.parent
_SNAPSHOT_ROOT = _TESTS_DIR / "fixtures" / "snapshots"

# ---------------------------------------------------------------------------
# V1_FIXTURES: list of (yaml_path, golden_dir) tuples.
#
# Each entry is a pre-v2 config that must remain byte-identical across all
# v2 work.  Add new pre-v2 configs here as they are discovered.
# ---------------------------------------------------------------------------
V1_FIXTURES = [
    (
        _REPO_ROOT / "examples" / "project.full.yaml",
        _SNAPSHOT_ROOT / "project_full",
    ),
]


def _render(yaml_path: Path) -> dict[str, str]:
    """Load and render a config YAML; return {rel_path: content}."""
    cfg = load(yaml_path)
    renderer = TemplateRenderer()
    return {str(p): content for p, content in renderer.render_all(cfg)}


# Parametrize by the YAML stem so pytest output names the fixture clearly.
@pytest.mark.parametrize(
    "yaml_path,golden_dir",
    V1_FIXTURES,
    ids=[p.stem for p, _ in V1_FIXTURES],
)
def test_v1_fixture_byte_identical(yaml_path: Path, golden_dir: Path) -> None:
    """Render a pre-v2 config and assert byte-identity against its golden tree.

    Assertions:
    1. The set of rendered files equals the set of golden files — neither side
       has extras.  Extra files in the rendered output indicate a v2 feature
       leaked into the legacy path.
    2. Every rendered file is byte-identical to its golden counterpart.

    This test never auto-updates.  It is intentionally rigid.
    """
    assert yaml_path.exists(), (
        f"V1 fixture YAML not found: {yaml_path}. "
        f"This is a configuration error in V1_FIXTURES."
    )
    assert golden_dir.exists(), (
        f"Golden tree directory not found: {golden_dir}. "
        f"The golden tree must be committed to the repository. "
        f"Render the fixture manually and commit the output to {golden_dir}."
    )

    rendered = _render(yaml_path)

    rendered_paths: set[str] = set(rendered.keys())

    all_golden_files = [f for f in golden_dir.rglob("*") if f.is_file()]
    contamination = [
        str(f.relative_to(golden_dir))
        for f in all_golden_files
        if "__pycache__" in f.parts or f.suffix == ".pyc"
    ]
    assert not contamination, (
        f"Golden tree is contaminated with bytecode artifacts: "
        f"{sorted(contamination)}. These must be removed from the committed "
        f"golden tree (they are machine/Python-version-specific and will drift)."
    )

    golden_paths: set[str] = {
        str(f.relative_to(golden_dir)) for f in all_golden_files
    }

    # --- set-equality assertions -------------------------------------------
    missing_from_render = golden_paths - rendered_paths
    extra_in_render = rendered_paths - golden_paths

    set_errors: list[str] = []
    if missing_from_render:
        set_errors.append(
            f"Files in golden tree but MISSING from render "
            f"({len(missing_from_render)}):\n"
            + "\n".join(f"  - {p}" for p in sorted(missing_from_render))
        )
    if extra_in_render:
        set_errors.append(
            f"Files in render but MISSING from golden tree "
            f"({len(extra_in_render)}) — "
            f"possible v2 feature leak into legacy path:\n"
            + "\n".join(f"  + {p}" for p in sorted(extra_in_render))
        )
    if set_errors:
        pytest.fail(
            f"File-set mismatch for fixture '{yaml_path.name}':\n\n"
            + "\n\n".join(set_errors)
        )

    # --- byte-identity per file --------------------------------------------
    differing: list[str] = []
    for rel_path in sorted(rendered_paths):
        golden_content = (golden_dir / rel_path).read_text(encoding="utf-8")
        rendered_content = rendered[rel_path]
        if golden_content != rendered_content:
            differing.append(rel_path)

    if differing:
        pytest.fail(
            f"Byte-identity failure for fixture '{yaml_path.name}'. "
            f"v2 is NOT shippable until these are resolved.\n\n"
            f"Files with content drift ({len(differing)}):\n"
            + "\n".join(f"  ! {p}" for p in differing)
            + "\n\nTo investigate: compare rendered output against "
            f"{golden_dir}/<file>.\n"
            "To update the golden tree, use test_scaffold_snapshot.py with "
            "UPDATE_SNAPSHOTS=1 (for default_scaffold) or update manually. "
            "DO NOT modify this test to auto-update."
        )
