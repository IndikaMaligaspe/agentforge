"""
Schema export drift guard.

Compares the committed agentforge/schema/project.schema.json against the
schema generated at runtime from the current Pydantic models. If they differ,
the test fails with an actionable message.

Fix: run `python scripts/export_schema.py` and commit the result.
"""
from __future__ import annotations

import json
from pathlib import Path

from agentforge.schema.models import ProjectConfig

SCHEMA_PATH = Path(__file__).parent.parent.parent / "agentforge" / "schema" / "project.schema.json"


def test_schema_export_matches_committed_file() -> None:
    """Runtime schema must match the committed project.schema.json byte-for-byte."""
    assert SCHEMA_PATH.exists(), (
        f"Committed schema file not found at {SCHEMA_PATH}. "
        "Run `python scripts/export_schema.py` to generate it."
    )

    committed = json.loads(SCHEMA_PATH.read_text())
    current = ProjectConfig.model_json_schema()

    assert committed == current, (
        "Schema export drifted from committed project.schema.json. "
        "Re-run `python scripts/export_schema.py` and commit the result."
    )
