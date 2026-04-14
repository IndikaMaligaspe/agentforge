"""Export the ProjectConfig JSON schema to agentforge/schema/project.schema.json.

Run from the repo root:
    python scripts/export_schema.py

The drift guard test (tests/schema/test_schema_export_drift.py) will fail if
the committed file is out of sync with the current Pydantic models. Re-run this
script and commit the result to fix it.
"""
import json
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path("agentforge/schema/project.schema.json")


def serialize_schema(config_class: Any) -> str:
    """Return the canonical serialized JSON schema string for *config_class*.

    This is the single source of truth for the serialization format used by
    both the export script and the drift guard tests.  The returned string ends
    with a trailing newline so it can be written directly to disk.
    """
    schema = config_class.model_json_schema()
    return json.dumps(schema, indent=2) + "\n"


def main() -> None:
    from agentforge.schema.models import ProjectConfig

    SCHEMA_PATH.write_text(serialize_schema(ProjectConfig))
    print(f"Schema written to {SCHEMA_PATH}")


if __name__ == "__main__":
    main()
