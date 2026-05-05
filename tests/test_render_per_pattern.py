"""
tests/test_render_per_pattern.py — Per-pattern render + compile + snapshot tests.

For each of the 5 example YAML fixtures:
  1. Load the config via schema.loader.load().
  2. Render via TemplateRenderer into an in-memory dict {rel_path: content}.
  3. compile() every .py file — stricter than ast.parse(); catches syntax errors
     AND some bytecode-generation issues that ast.parse() misses.
  4. Compare a sha256 manifest of rendered files against a committed snapshot at
     tests/snapshots/per_pattern/{name}/manifest.json.

Convention: when UPDATE_SNAPSHOTS=1 is set in the environment, manifests are
written/updated and the test is skipped — identical to test_scaffold_snapshot.py.

Design:
  - Manifest format: {"files": {"<rel_path>": "<sha256_hex>"}}, sorted keys,
    pretty-printed (2-space indent) so git diffs are readable.
  - Hash: sha256(content.encode("utf-8")).hexdigest()
  - Parametrization iterates the _EXAMPLE_FILES list so test IDs are stable.
  - Failure messages show a unified diff of file lists and names of files whose
    hashes changed, so failures are immediately actionable.
"""
from __future__ import annotations

import difflib
import json
import os
import warnings
from hashlib import sha256
from pathlib import Path

import pytest

from agentforge.engine.renderer import TemplateRenderer
from agentforge.schema.loader import load

# Root of examples/ directory.
_EXAMPLES_DIR: Path = Path(__file__).parent.parent / "examples"

# Snapshot root for this test suite.
_SNAPSHOT_ROOT: Path = Path(__file__).parent / "snapshots" / "per_pattern"

# The 5 example files.  project.full.yaml is intentionally
# excluded — it is governed by tests/test_scaffold_snapshot.py.
_EXAMPLE_FILES = [
    "assistant.yaml",
    "copilot.yaml",
    "planner.yaml",
    "fanout.yaml",
    "workflow.yaml",
]

# Bare name used as directory key and test ID, e.g. "copilot".
_EXAMPLE_IDS = [Path(f).stem for f in _EXAMPLE_FILES]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _render_to_dict(example_yaml: Path) -> dict[str, str]:
    """Load *example_yaml* and render it to an in-memory {rel_path: content} dict."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        cfg = load(example_yaml)
    renderer = TemplateRenderer()
    return {str(rel_path): content for rel_path, content in renderer.render_all(cfg)}


def _compute_manifest(rendered: dict[str, str]) -> dict[str, str]:
    """Return a {rel_path: sha256_hex} dict for all rendered files, sorted by key."""
    return {
        rel_path: sha256(content.encode("utf-8")).hexdigest()
        for rel_path, content in sorted(rendered.items())
    }


def _manifest_path(name: str) -> Path:
    """Return the manifest JSON path for *name* (bare stem, e.g. 'copilot')."""
    return _SNAPSHOT_ROOT / name / "manifest.json"


def _write_manifest(name: str, manifest: dict[str, str]) -> None:
    """Write *manifest* to the canonical snapshot path for *name*."""
    mp = _manifest_path(name)
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(
        json.dumps({"files": manifest}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_manifest(name: str) -> dict[str, str]:
    """Load and return the stored manifest dict for *name*. Raises if missing."""
    mp = _manifest_path(name)
    data = json.loads(mp.read_text(encoding="utf-8"))
    return data["files"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", params=_EXAMPLE_FILES, ids=_EXAMPLE_IDS)
def example_rendered(request: pytest.FixtureRequest) -> tuple[str, dict[str, str]]:
    """
    Module-scoped fixture: renders one example yaml and returns
    ``(bare_name, {rel_path: content})``.

    Module scope is intentional: rendering is the expensive part, and both
    test functions for the same fixture share the same output.
    """
    filename: str = request.param
    name = Path(filename).stem
    rendered = _render_to_dict(_EXAMPLES_DIR / filename)
    return name, rendered


# ---------------------------------------------------------------------------
# Test: compile() every .py file
# ---------------------------------------------------------------------------


def test_pattern_compiles(example_rendered: tuple[str, dict[str, str]]) -> None:
    """
    compile(src, path, "exec") must succeed for every generated .py file.

    compile() is stricter than ast.parse(): it catches syntax errors AND
    bytecode-generation issues such as duplicate argument names, invalid
    augmented assignments to non-local names, etc.
    """
    name, rendered = example_rendered
    failures: list[str] = []
    for rel_path, content in sorted(rendered.items()):
        if not rel_path.endswith(".py"):
            continue
        try:
            compile(content, rel_path, "exec")
        except SyntaxError as exc:
            failures.append(f"  {rel_path}: {exc}")

    assert not failures, (
        f"Pattern '{name}': generated .py files failed compile():\n"
        + "\n".join(failures)
    )


# ---------------------------------------------------------------------------
# Test: snapshot manifest comparison
# ---------------------------------------------------------------------------


def test_pattern_snapshot_matches(
    example_rendered: tuple[str, dict[str, str]],
) -> None:
    """
    The sha256 manifest of the rendered scaffold must match the committed snapshot.

    When UPDATE_SNAPSHOTS=1 is set: write/update the manifest and skip.
    When the snapshot is missing: write it and skip (first-run bootstrap).

    Failure messages include:
      - Files present in snapshot but missing from current render.
      - Files present in current render but missing from snapshot.
      - Names of files whose hashes changed.
    """
    name, rendered = example_rendered
    current_manifest = _compute_manifest(rendered)

    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        _write_manifest(name, current_manifest)
        pytest.skip(f"Snapshots updated for '{name}' — review diff and commit.")

    mp = _manifest_path(name)
    if not mp.exists():
        _write_manifest(name, current_manifest)
        pytest.skip(
            f"Snapshot for '{name}' did not exist; created at {mp}. "
            "Re-run tests after committing."
        )

    stored_manifest = _load_manifest(name)

    stored_paths = set(stored_manifest.keys())
    current_paths = set(current_manifest.keys())

    missing_in_current = stored_paths - current_paths
    extra_in_current = current_paths - stored_paths

    # Files whose hashes changed (present in both sets).
    common_paths = stored_paths & current_paths
    changed = sorted(
        p for p in common_paths if stored_manifest[p] != current_manifest[p]
    )

    problems: list[str] = []

    if missing_in_current:
        diff_lines = list(
            difflib.unified_diff(
                sorted(missing_in_current),
                [],
                fromfile=f"snapshot/{name}",
                tofile=f"rendered/{name}",
                lineterm="",
            )
        )
        problems.append(
            "Files in snapshot but MISSING from current render:\n"
            + "\n".join(f"  - {p}" for p in sorted(missing_in_current))
        )
        if diff_lines:
            problems.append("Diff:\n" + "\n".join(diff_lines[:40]))

    if extra_in_current:
        problems.append(
            "Files in current render but NOT in snapshot (new files):\n"
            + "\n".join(f"  + {p}" for p in sorted(extra_in_current))
            + "\n(Run with UPDATE_SNAPSHOTS=1 if this is intentional.)"
        )

    if changed:
        problems.append(
            "Files whose hashes changed:\n"
            + "\n".join(f"  ~ {p}" for p in changed)
            + "\n(Run with UPDATE_SNAPSHOTS=1 to regenerate.)"
        )

    assert not problems, (
        f"Snapshot mismatch for pattern '{name}':\n\n"
        + "\n\n".join(problems)
    )
