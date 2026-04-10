"""Regression snapshot test: default scaffold output must not drift."""
import os
from pathlib import Path
import difflib
import pytest
from agentforge.schema.loader import load
from agentforge.engine.renderer import TemplateRenderer

SNAPSHOT_DIR = Path(__file__).parent / "fixtures" / "snapshots" / "default_scaffold"
FIXTURE = Path(__file__).parent / "fixtures" / "full.yaml"


def _render_default() -> dict[str, str]:
    cfg = load(FIXTURE)
    assert cfg.observability.structured_logging is False
    assert cfg.workflow.router_llm_provider == "openai"
    assert cfg.enable_provider_registry is False
    r = TemplateRenderer()
    return {str(p): c for p, c in r.render_all(cfg)}


def _update_snapshots(rendered: dict[str, str]) -> None:
    # Wipe and rewrite
    if SNAPSHOT_DIR.exists():
        for f in sorted(SNAPSHOT_DIR.rglob("*")):
            if f.is_file():
                f.unlink()
    for rel_path, content in rendered.items():
        out = SNAPSHOT_DIR / rel_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content)


def test_default_scaffold_matches_snapshot():
    rendered = _render_default()

    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        _update_snapshots(rendered)
        pytest.skip("Snapshots updated — review diff and commit the result.")

    if not SNAPSHOT_DIR.exists():
        _update_snapshots(rendered)
        pytest.skip(
            f"Snapshot directory did not exist; created from current render at "
            f"{SNAPSHOT_DIR}. Re-run tests after committing."
        )

    # Check file set
    rendered_paths = set(rendered.keys())
    snapshot_paths = {
        str(p.relative_to(SNAPSHOT_DIR))
        for p in SNAPSHOT_DIR.rglob("*")
        if p.is_file()
    }

    missing_in_rendered = snapshot_paths - rendered_paths
    extra_in_rendered = rendered_paths - snapshot_paths
    assert not missing_in_rendered, (
        f"Files present in snapshot but missing from current render: "
        f"{sorted(missing_in_rendered)}"
    )
    assert not extra_in_rendered, (
        f"Files present in current render but missing from snapshot: "
        f"{sorted(extra_in_rendered)}. "
        f"Run with UPDATE_SNAPSHOTS=1 if this is intentional."
    )

    # Byte-identity per file, sorted for deterministic failure ordering
    for rel_path in sorted(rendered_paths):
        expected = (SNAPSHOT_DIR / rel_path).read_text()
        actual = rendered[rel_path]
        if expected != actual:
            diff = "\n".join(
                difflib.unified_diff(
                    expected.splitlines(),
                    actual.splitlines(),
                    fromfile=f"snapshot/{rel_path}",
                    tofile=f"rendered/{rel_path}",
                    lineterm="",
                )
            )
            # Show only the first ~40 lines of the first diff
            diff_head = "\n".join(diff.splitlines()[:40])
            pytest.fail(
                f"Snapshot drift in {rel_path}:\n{diff_head}\n"
                f"(Run with UPDATE_SNAPSHOTS=1 to regenerate.)"
            )
