"""
Schema export drift guard.

Compares the committed agentforge/schema/project.schema.json against the
schema generated at runtime from the current Pydantic models.  If any check
fails, the fix is:

    python scripts/export_schema.py   # regenerate
    git add agentforge/schema/project.schema.json
    git commit -m "chore: sync schema export"
"""
from __future__ import annotations

import json
from pathlib import Path

from agentforge.schema.models import ProjectConfig
from scripts.export_schema import serialize_schema

SCHEMA_PATH = Path(__file__).parent.parent.parent / "agentforge" / "schema" / "project.schema.json"

# ---------------------------------------------------------------------------
# V2 contract: the sets below are the explicit public API surface added in v2.
# If you remove a key from the schema, update this list AND bump the schema
# version so downstream consumers are aware of the breaking change.
# ---------------------------------------------------------------------------
EXPECTED_V2_KEYS_AT_ROOT = {"entry", "pattern", "react", "fanout", "workflow_sm", "orchestrator", "planner"}
EXPECTED_V2_DEFS = {
    "EntryConfig",
    "ReactConfig",
    "WorkflowStateMachineConfig",
    "FanoutConfig",
    "OrchestratorConfig",
    "PlannerConfig",
    "StepConfig",
    "HttpTool",
    "AgentTool",
    "McpTool",
}


def test_schema_export_semantic_match() -> None:
    """Runtime schema must be semantically equal to the committed project.schema.json.

    Uses json.loads comparison so key-ordering or whitespace differences in the
    committed file do not cause false failures here — that is the job of the
    byte-identity check below.
    """
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


def test_schema_export_byte_identical() -> None:
    """Committed file bytes must match serialize_schema(ProjectConfig) exactly.

    This catches formatting drift: if someone hand-edits indentation or
    key ordering in the committed JSON, the semantic check passes but this
    check fails — indicating the file is no longer canonical.
    """
    assert SCHEMA_PATH.exists(), (
        f"Committed schema file not found at {SCHEMA_PATH}. "
        "Run `python scripts/export_schema.py` to generate it."
    )

    committed_bytes = SCHEMA_PATH.read_bytes()
    expected_bytes = serialize_schema(ProjectConfig).encode()

    assert committed_bytes == expected_bytes, (
        "Committed project.schema.json is not byte-identical to serialize_schema(ProjectConfig). "
        "Re-run `python scripts/export_schema.py` and commit the result."
    )


def test_schema_export_idempotent() -> None:
    """Calling ProjectConfig.model_json_schema() twice must return equal output.

    This is a cheap sanity guard against Pydantic regressions where schema
    generation has side-effects that mutate the model on first call.
    """
    first = ProjectConfig.model_json_schema()
    second = ProjectConfig.model_json_schema()

    assert first == second, (
        "ProjectConfig.model_json_schema() is not idempotent — "
        "two successive calls returned different results.  "
        "This indicates a Pydantic schema-generation bug."
    )


def test_schema_contains_v2_additions() -> None:
    """Committed schema must contain all v2 top-level keys and $defs entries.

    This is a defensive regression guard: if a refactor accidentally removes
    a v2 primitive from the schema, this test catches it immediately.
    """
    data = json.loads(SCHEMA_PATH.read_text())
    props = set(data.get("properties", {}).keys())
    defs = set(data.get("$defs", {}).keys())

    missing_props = EXPECTED_V2_KEYS_AT_ROOT - props
    assert not missing_props, (
        f"V2 top-level properties missing from schema: {sorted(missing_props)}. "
        "Check agentforge/schema/models.py and re-run `python scripts/export_schema.py`."
    )

    missing_defs = EXPECTED_V2_DEFS - defs
    assert not missing_defs, (
        f"V2 $defs missing from schema: {sorted(missing_defs)}. "
        "Check agentforge/schema/models.py and re-run `python scripts/export_schema.py`."
    )
