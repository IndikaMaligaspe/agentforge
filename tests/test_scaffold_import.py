"""
Real-scaffold import tests.

Walk every generated .py file in a scaffolded project and import it via
importlib. Catches ImportError, AttributeError, missing packages, and
module-level runtime errors that ast.parse cannot detect.

Two scenarios:
  - test_scaffold_imports_with_all_flags_off: full.yaml (stdlib logging,
    openai router, no provider registry)
  - test_scaffold_imports_with_all_flags_on:  all_flags_on.yaml (structlog,
    anthropic router, provider registry)

Requires the scaffold-test extra from pyproject.toml to be installed:
    ./test_env/bin/pip install -e '.[scaffold-test]'
If the extra's deps are missing, both tests skip with a clear message.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
import tempfile
import warnings
from pathlib import Path

import pytest

from agentforge.engine.renderer import TemplateRenderer
from agentforge.schema.loader import load
from agentforge.writer.scaffold import ScaffoldWriter

FIXTURES = Path(__file__).parent / "fixtures"
FULL_YAML = FIXTURES / "full.yaml"
ALL_FLAGS_ON_YAML = FIXTURES / "all_flags_on.yaml"

REQUIRED_DEPS = [
    "fastapi",
    "langgraph",
    "langchain_openai",
    "langchain_anthropic",
    "structlog",
    "yaml",
]


def _require_deps() -> None:
    missing = [d for d in REQUIRED_DEPS if importlib.util.find_spec(d) is None]
    if missing:
        pytest.skip(
            f"Scaffolded-project runtime deps are missing: {missing}. "
            f"Run: ./test_env/bin/pip install -e '.[scaffold-test]'"
        )


def _scaffold(fixture_path: Path, tmpdir: Path) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        cfg = load(fixture_path)
    renderer = TemplateRenderer()
    writer = ScaffoldWriter(root=tmpdir, overwrite=True)
    for rel_path, content in renderer.render_all(cfg):
        writer.write(rel_path, content)


def _walk_and_import_all(tmpdir: Path) -> list[str]:
    failures: list[str] = []
    backend_root = tmpdir / "backend"
    for py_file in sorted(backend_root.rglob("*.py")):
        rel = py_file.relative_to(tmpdir)
        parts = rel.with_suffix("").parts
        if parts[-1] == "__init__":
            continue
        module_name = ".".join(parts)
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            failures.append(f"{module_name}: {type(exc).__name__}: {exc}")
    return failures


def _cleanup(added_paths: list[str]) -> None:
    for p in added_paths:
        try:
            sys.path.remove(p)
        except ValueError:
            pass
    stale = [
        k for k in list(sys.modules)
        if k == "backend" or k.startswith("backend.")
    ]
    for key in stale:
        del sys.modules[key]


def _run_scenario(fixture_path: Path) -> None:
    _require_deps()
    with tempfile.TemporaryDirectory(prefix="agentforge_import_test_") as tmpdir_str:
        tmpdir = Path(tmpdir_str)
        _scaffold(fixture_path, tmpdir)
        root_dir = str(tmpdir)
        backend_dir = str(tmpdir / "backend")
        sys.path.insert(0, backend_dir)
        sys.path.insert(0, root_dir)
        added = [root_dir, backend_dir]
        try:
            failures = _walk_and_import_all(tmpdir)
            if failures:
                msg = "Scaffolded modules failed to import:\n"
                for f in failures:
                    msg += f"  - {f}\n"
                pytest.fail(msg)
        finally:
            _cleanup(added)


def test_scaffold_imports_with_all_flags_off():
    _run_scenario(FULL_YAML)


def test_scaffold_imports_with_all_flags_on():
    _run_scenario(ALL_FLAGS_ON_YAML)
