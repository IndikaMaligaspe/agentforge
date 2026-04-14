"""
tests/e2e/conftest.py — Shared helpers for the e2e test suite.

Extracted so both test_full_scaffold.py (project.full.yaml-specific assertions)
and test_v2_patterns.py (generic parametrized checks over the 6 v2 example files)
can share the render helper and FORBIDDEN_STRINGS list without duplication.
"""
from __future__ import annotations

import warnings
from pathlib import Path

from agentforge.engine.renderer import TemplateRenderer
from agentforge.schema.loader import load
from agentforge.writer.scaffold import ScaffoldWriter

# Strings that must never appear in any generated file, regardless of pattern.
FORBIDDEN_STRINGS: list[str] = ["madgicx", "slack", "webhook"]


def render_yaml_to_dict(yaml_path: Path, tmpdir: Path | None = None) -> dict[str, str]:
    """
    Load *yaml_path* via the schema loader, render all files, and return
    ``{rel_path_str: content}`` in-memory.

    When *tmpdir* is provided the files are also written to disk via
    ScaffoldWriter (needed for tests that inspect the filesystem).  When
    omitted the output is in-memory only (sufficient for AST/content checks).
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        cfg = load(yaml_path)
    renderer = TemplateRenderer()
    rendered: dict[str, str] = {}
    if tmpdir is not None:
        writer = ScaffoldWriter(root=tmpdir, overwrite=True)
        for rel_path, content in renderer.render_all(cfg):
            writer.write(rel_path, content)
            rendered[str(rel_path)] = content
    else:
        for rel_path, content in renderer.render_all(cfg):
            rendered[str(rel_path)] = content
    return rendered
