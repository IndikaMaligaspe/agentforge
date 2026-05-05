"""
tests/e2e/test_v2_patterns.py — Generic e2e checks for all 5 v2 pattern fixtures.

Scope
-----
Runs the same battery of structural checks against each of the 5 example YAML
files:

    assistant, copilot, planner, fanout, workflow

Design decision (documented here per the plan):
    The "deep" form of the acceptance criterion — install deps, run pytest inside
    the generated project — is too expensive for CI (would require a fresh
    ``pip install`` per pattern per test run).  This module therefore uses the
    "cheap" form:

      1. Render the scaffold in-memory (no disk write needed for most checks).
      2. AST-compile every generated .py file with compile() — stricter than
         ast.parse() because it also catches bytecode-generation errors.
      3. Assert required top-level files are present and non-empty.
      4. Assert no forbidden strings appear in any file.
      5. Sweep import statements vs requirements.txt to verify that every
         third-party package imported by generated code is declared as a
         runtime dependency.

    A full smoke test that pip-installs and pytest-executes the generated
    project is out of scope here to avoid CI cost; if added later, gate it
    behind a dedicated pytest marker registered in ``pyproject.toml``.

Import → requirements mapping
------------------------------
The mapping below is the single source of truth for "if import X appears in any
generated .py, then Y must appear in requirements.txt".  Standard-library modules
and intra-project imports (``backend.*``, ``agents``, ``graph``, etc.) are
excluded from the check — only third-party packages that a user would need to
``pip install`` are mapped.

    import name              → requirements.txt substring
    -------------------------------------------------------
    langchain_openai         → langchain-openai
    langchain_core           → langchain-core
    langchain_mcp_adapters   → langchain-mcp-adapters
    langgraph                → langgraph
    langfuse                 → langfuse
    httpx                    → httpx
    jwt                      → pyjwt
    alembic                  → alembic
    deepeval                 → deepeval
    psycopg                  → psycopg
    pydantic                 → pydantic
    fastapi                  → fastapi
    dotenv                   → python-dotenv
    structlog                → structlog
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tests.e2e.conftest import FORBIDDEN_STRINGS, render_yaml_to_dict

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EXAMPLES_DIR = Path(__file__).parent.parent.parent / "examples"

# The 5 v2 pattern fixture files (project.full.yaml is governed by
# test_full_scaffold.py and intentionally excluded here).
_EXAMPLE_FILES = [
    "assistant.yaml",
    "copilot.yaml",
    "planner.yaml",
    "fanout.yaml",
    "workflow.yaml",
]

_EXAMPLE_IDS = [Path(f).stem for f in _EXAMPLE_FILES]

# Required top-level files that every rendered scaffold must contain and that
# must be non-empty.
_REQUIRED_TOP_LEVEL_FILES = [
    "requirements.txt",
    ".env.example",
    "Makefile",
    "backend/main.py",
]

# Mapping from Python top-level import module name to the substring that must
# appear in requirements.txt.  Standard-library modules and intra-project
# imports are intentionally absent — only third-party pip-installable packages.
_IMPORT_TO_REQUIREMENT: dict[str, str] = {
    "langchain_openai": "langchain-openai",
    "langchain_core": "langchain-core",
    "langchain_mcp_adapters": "langchain-mcp-adapters",
    "langgraph": "langgraph",
    "langfuse": "langfuse",
    "httpx": "httpx",
    "jwt": "pyjwt",
    "alembic": "alembic",
    "deepeval": "deepeval",
    "psycopg": "psycopg",
    "pydantic": "pydantic",
    "fastapi": "fastapi",
    "dotenv": "python-dotenv",
    "structlog": "structlog",
}


# ---------------------------------------------------------------------------
# Module-scoped fixture — render each example once and share across test fns
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", params=_EXAMPLE_FILES, ids=_EXAMPLE_IDS)
def v2_pattern_rendered(request: pytest.FixtureRequest) -> tuple[str, dict[str, str]]:
    """
    Module-scoped fixture: renders one v2 example yaml and returns
    ``(bare_name, {rel_path: content})``.

    Module scope is intentional — rendering is the expensive step, and all
    five test functions for a given fixture share the same in-memory output.
    """
    filename: str = request.param
    name = Path(filename).stem
    rendered = render_yaml_to_dict(_EXAMPLES_DIR / filename)
    return name, rendered


# ---------------------------------------------------------------------------
# Test: scaffold renders (all non-init files non-empty)
# ---------------------------------------------------------------------------


def test_e2e_example_renders(v2_pattern_rendered: tuple[str, dict[str, str]]) -> None:
    """
    The scaffold must render at least one file, and every rendered file
    (excluding ``__init__.py`` package markers) must have non-empty content.

    ``__init__.py`` files are intentionally empty in many Python projects and
    are therefore exempt from the non-empty check.  All other files must
    contain at least one non-whitespace character — an empty substantive file
    indicates a rendering bug (e.g. a template that emitted nothing).
    """
    name, rendered = v2_pattern_rendered
    assert rendered, f"Pattern '{name}': scaffold rendered no files at all"
    # __init__.py files are legitimately empty package markers — skip them.
    empty_files = [
        path
        for path, content in rendered.items()
        if not content.strip() and not path.endswith("__init__.py")
    ]
    assert not empty_files, (
        f"Pattern '{name}': the following non-init files rendered as empty:\n"
        + "\n".join(f"  {p}" for p in sorted(empty_files))
    )


# ---------------------------------------------------------------------------
# Test: all .py files compile
# ---------------------------------------------------------------------------


def test_e2e_example_all_py_compiles(
    v2_pattern_rendered: tuple[str, dict[str, str]],
) -> None:
    """
    compile(src, path, "exec") must succeed for every generated .py file.

    compile() is stricter than ast.parse(): it catches syntax errors AND
    bytecode-generation issues such as duplicate argument names, invalid
    augmented assignments to non-local names, etc.
    """
    name, rendered = v2_pattern_rendered
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
# Test: required top-level files present and non-empty
# ---------------------------------------------------------------------------


def test_e2e_example_required_files_present(
    v2_pattern_rendered: tuple[str, dict[str, str]],
) -> None:
    """
    Every scaffold must contain requirements.txt, .env.example, Makefile, and
    backend/main.py, and each of those files must be non-empty.
    """
    name, rendered = v2_pattern_rendered
    missing: list[str] = []
    empty: list[str] = []
    for required in _REQUIRED_TOP_LEVEL_FILES:
        if required not in rendered:
            missing.append(required)
        elif not rendered[required].strip():
            empty.append(required)

    problems: list[str] = []
    if missing:
        problems.append(
            "Missing files:\n" + "\n".join(f"  - {f}" for f in missing)
        )
    if empty:
        problems.append(
            "Present but empty:\n" + "\n".join(f"  - {f}" for f in empty)
        )

    assert not problems, (
        f"Pattern '{name}': required files check failed:\n\n"
        + "\n\n".join(problems)
    )


# ---------------------------------------------------------------------------
# Test: no forbidden strings
# ---------------------------------------------------------------------------


def test_e2e_example_no_forbidden_strings(
    v2_pattern_rendered: tuple[str, dict[str, str]],
) -> None:
    """
    No generated file may contain any of the forbidden strings
    (madgicx, slack, webhook) — case-insensitive.
    """
    name, rendered = v2_pattern_rendered
    violations: list[str] = []
    for rel_path, content in sorted(rendered.items()):
        for forbidden in FORBIDDEN_STRINGS:
            if re.search(forbidden, content, re.IGNORECASE):
                violations.append(f"  {rel_path}: contains '{forbidden}'")

    assert not violations, (
        f"Pattern '{name}': forbidden strings found in scaffold:\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Test: imports match requirements.txt
# ---------------------------------------------------------------------------


def _collect_top_level_imports(source: str) -> set[str]:
    """
    Parse *source* as Python and return the set of top-level module names
    referenced by ``import X`` or ``from X import ...`` statements.

    Returns an empty set if the source fails to parse (callers handle syntax
    errors separately in test_e2e_example_all_py_compiles).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".")[0])
    return names


def test_e2e_example_imports_match_requirements(
    v2_pattern_rendered: tuple[str, dict[str, str]],
) -> None:
    """
    Every third-party import found in generated .py files must be declared as
    a runtime dependency in requirements.txt.

    The check is performed via _IMPORT_TO_REQUIREMENT, a curated mapping from
    Python import module name to the package name substring expected in
    requirements.txt.  Standard-library modules and intra-project imports are
    not in the mapping and are therefore not checked.

    Note: this check is one-directional — it catches "imported but not
    declared" only.  Packages declared in requirements.txt but never imported
    are NOT flagged.  A separate stale-dep test would be needed for that
    coverage.

    This verifies that the template author did not accidentally add an import
    without updating the requirements template.
    """
    name, rendered = v2_pattern_rendered

    # Collect all third-party top-level imports used across every .py file.
    used_imports: set[str] = set()
    for rel_path, content in rendered.items():
        if not rel_path.endswith(".py"):
            continue
        used_imports |= _collect_top_level_imports(content)

    requirements_txt = rendered.get("requirements.txt", "")

    violations: list[str] = []
    for import_name, req_substring in _IMPORT_TO_REQUIREMENT.items():
        if import_name in used_imports and req_substring not in requirements_txt:
            violations.append(
                f"  import '{import_name}' used in generated .py files "
                f"but '{req_substring}' not found in requirements.txt"
            )

    assert not violations, (
        f"Pattern '{name}': import/requirements mismatch:\n"
        + "\n".join(violations)
    )
