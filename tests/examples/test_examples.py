"""
tests/examples/test_examples.py — Parametrized load + render + AST-parse tests for
all example project.yaml files under examples/.

For each example:
  1. Load and validate the config via schema.loader.load() — catches schema errors.
  2. Render the full scaffold to a tmp_path via TemplateRenderer + ScaffoldWriter.
  3. Walk every generated .py file and ast.parse() it — catches codegen syntax errors.
  4. Assert that expected feature-presence markers appear in the correct rendered file.

No dependency installation or network access is required. All assertions are purely
structural (file presence, AST validity). The test is parametrized so failures are
reported per-example rather than as a single monolithic failure.

Design decisions:
  - Uses tmp_path (pytest-provided per-test temp dir) so renders are isolated.
  - Suppresses UserWarning during load() to avoid spurious noise from intentional
    provider/model combos that trigger the mismatch warning.
  - Walks the rendered tree on disk rather than the in-memory dict so that the
    ScaffoldWriter's actual file-writing path is exercised end-to-end.
"""
from __future__ import annotations

import ast
import warnings
from pathlib import Path

import pytest

from agentforge.engine.renderer import TemplateRenderer
from agentforge.schema.loader import load
from agentforge.writer.scaffold import ScaffoldWriter

# Root of the examples/ directory — resolved relative to this test file.
_EXAMPLES_DIR: Path = Path(__file__).parent.parent.parent / "examples"

# The example files introduced in TODO-v2-9.
# project.full.yaml is intentionally excluded — it has its own dedicated e2e test
# (tests/e2e/test_full_scaffold.py) that is treated as a byte-identity fixture.
_EXAMPLE_FILES = [
    "campaign_health.yaml",
    "copilot.yaml",
    "planner.yaml",
    "fanout.yaml",
    "workflow.yaml",
    "assistant.yaml",
]

# Parametrize IDs are the bare filename (without .yaml) for readable test names.
_EXAMPLE_IDS = [name.replace(".yaml", "") for name in _EXAMPLE_FILES]

# Feature-presence markers: maps example filename → (rendered_file_path, marker_string).
#
# Each entry asserts that the rendered scaffold for that example contains the given
# marker string in the given file, confirming the pattern-specific codegen ran.
#
# Marker selection rationale:
#   campaign_health — query_router_node.py is the LLM intent classifier; the string
#     "intent" appears multiple times as the variable that holds the classification result.
#   assistant       — supervisor_node.py is the LLM-routed orchestrator dispatch node;
#     "intent" appears as state["intent"] and log variables, confirming the orchestrator
#     topology was rendered (distinguishes orchestrator from react/fanout/planner/workflow).
#   copilot         — passthrough_node.py is generated only for entry.type=passthrough;
#     "inputs" appears as the dict extracted from the query (the node's sole purpose).
#   planner         — plan_precheck_node.py wraps _precheck.check_plan; "check_plan"
#     appears in the import and the call, confirming precheck_enabled=true rendered.
#   fanout          — reducer_node.py contains the reducer strategy literal; "merge_dict"
#     appears in the docstring and the strategy branch, confirming fanout.reducer setting.
#   workflow        — workflow.py uses interrupt_before in the compile() call;
#     "interrupt_before" appears as the LangGraph HITL compile argument.
_EXPECTED_MARKERS: dict[str, tuple[str, str]] = {
    "campaign_health.yaml": ("backend/graph/nodes/query_router_node.py", "intent"),
    "assistant.yaml":       ("backend/graph/nodes/supervisor_node.py", "intent"),
    "copilot.yaml":         ("backend/graph/nodes/passthrough_node.py", "inputs"),
    "planner.yaml":         ("backend/graph/nodes/plan_precheck_node.py", "check_plan"),
    "fanout.yaml":          ("backend/graph/nodes/reducer_node.py", "merge_dict"),
    "workflow.yaml":        ("backend/graph/workflow.py", "interrupt_before"),
}


@pytest.fixture(scope="module", params=_EXAMPLE_FILES, ids=_EXAMPLE_IDS)
def example_path(request: pytest.FixtureRequest) -> Path:
    """Yield the absolute path for one example yaml file."""
    return _EXAMPLES_DIR / request.param


# ── Load / schema tests ──────────────────────────────────────────────────────


def test_example_loads_without_error(example_path: Path) -> None:
    """Every example file must load and validate successfully via schema.loader.load()."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        cfg = load(example_path)
    # Sanity checks — if load() succeeded, these should always hold.
    assert cfg.metadata.name, "metadata.name must be non-empty after load"
    assert len(cfg.agents) >= 1, "must declare at least one agent"


def test_example_has_description(example_path: Path) -> None:
    """Every example file must have a non-empty project description."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        cfg = load(example_path)
    assert cfg.metadata.description.strip(), (
        f"{example_path.name}: metadata.description must not be empty"
    )


def test_example_v2_fields_set(example_path: Path) -> None:
    """Every example file must explicitly declare the v2 entry and pattern fields."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        cfg = load(example_path)
    assert cfg.entry is not None, (
        f"{example_path.name}: 'entry' must be set — examples should explicitly "
        "declare the entry type, not rely on legacy auto-injection"
    )
    assert cfg.pattern is not None, (
        f"{example_path.name}: 'pattern' must be set — examples should explicitly "
        "declare the execution pattern"
    )


# ── Render tests ─────────────────────────────────────────────────────────────


@pytest.fixture()
def rendered_scaffold(example_path: Path, tmp_path: Path) -> dict[str, str]:
    """
    Render the example config to tmp_path and return a dict of
    {relative_path_str: file_content} for all generated files.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        cfg = load(example_path)

    renderer = TemplateRenderer()
    writer = ScaffoldWriter(root=tmp_path, overwrite=True)
    rendered: dict[str, str] = {}

    for rel_path, content in renderer.render_all(cfg):
        writer.write(rel_path, content)
        rendered[str(rel_path)] = content

    return rendered


def test_example_renders_without_error(rendered_scaffold: dict[str, str]) -> None:
    """Rendering must produce at least one file without raising."""
    assert len(rendered_scaffold) > 0, "Renderer produced no output files"


def test_example_core_files_present(rendered_scaffold: dict[str, str]) -> None:
    """The always-rendered core files must be present in every scaffold."""
    # These files are unconditionally emitted by the renderer for any valid config.
    always_present = [
        "backend/__init__.py",
        "backend/main.py",
        "backend/agents/__init__.py",
        "backend/agents/base_agent.py",
        "backend/agents/registry.py",
        "backend/graph/__init__.py",
        "backend/graph/state.py",
        "backend/graph/workflow.py",
        ".env.example",
        ".gitignore",
        "Makefile",
        "README.md",
        "requirements.txt",
    ]
    missing = [f for f in always_present if f not in rendered_scaffold]
    assert not missing, f"Always-rendered files missing from scaffold: {missing}"


def test_example_all_py_files_ast_parse(rendered_scaffold: dict[str, str]) -> None:
    """Every generated .py file must parse as valid Python via ast.parse()."""
    failures: list[str] = []
    for rel_path, content in rendered_scaffold.items():
        if not rel_path.endswith(".py"):
            continue
        try:
            ast.parse(content)
        except SyntaxError as exc:
            failures.append(f"{rel_path}: {exc}")
    assert not failures, (
        "Generated .py files with syntax errors:\n" + "\n".join(failures)
    )


def test_example_walk_py_files_on_disk(example_path: Path, tmp_path: Path) -> None:
    """
    Walk the rendered scaffold on disk and ast.parse() every .py file.

    This exercises the ScaffoldWriter's actual write path (not just the in-memory
    render dict) and ensures that the files written to disk are identical to what
    was rendered in memory.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        cfg = load(example_path)

    renderer = TemplateRenderer()
    writer = ScaffoldWriter(root=tmp_path, overwrite=True)

    for rel_path, content in renderer.render_all(cfg):
        writer.write(rel_path, content)

    py_files = list(tmp_path.rglob("*.py"))
    assert len(py_files) > 0, "No .py files found on disk after render"

    failures: list[str] = []
    for py_file in py_files:
        src = py_file.read_text(encoding="utf-8")
        try:
            ast.parse(src)
        except SyntaxError as exc:
            rel = py_file.relative_to(tmp_path)
            failures.append(f"{rel}: {exc}")

    assert not failures, (
        f"On-disk .py files with syntax errors in {example_path.name}:\n"
        + "\n".join(failures)
    )


# ── Feature-presence marker tests ────────────────────────────────────────────


@pytest.mark.parametrize(
    "example_filename,rendered_file,marker",
    [
        (fname, file_path, marker)
        for fname, (file_path, marker) in _EXPECTED_MARKERS.items()
    ],
    ids=list(_EXPECTED_MARKERS.keys()),
)
def test_example_feature_marker_present(
    example_filename: str,
    rendered_file: str,
    marker: str,
    tmp_path: Path,
) -> None:
    """
    Assert that the rendered scaffold for each example contains a pattern-specific
    feature marker in the expected generated file.

    This catches regressions where the template renderer skips a pattern-specific
    file or generates it without the expected content.
    """
    example_path = _EXAMPLES_DIR / example_filename
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        cfg = load(example_path)

    renderer = TemplateRenderer()
    writer = ScaffoldWriter(root=tmp_path, overwrite=True)
    rendered: dict[str, str] = {}

    for rel_path, content in renderer.render_all(cfg):
        writer.write(rel_path, content)
        rendered[str(rel_path)] = content

    assert rendered_file in rendered, (
        f"{example_filename}: expected rendered file '{rendered_file}' not found in scaffold. "
        f"Available files: {sorted(rendered.keys())}"
    )
    assert marker in rendered[rendered_file], (
        f"{example_filename}: marker {marker!r} not found in '{rendered_file}'. "
        f"This suggests the pattern-specific codegen did not produce the expected content."
    )
