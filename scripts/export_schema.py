"""Export the ProjectConfig JSON schema to agentforge/schema/project.schema.json.

Run from the repo root:
    python scripts/export_schema.py

The drift guard test (tests/schema/test_schema_export_drift.py) will fail if
the committed file is out of sync with the current Pydantic models. Re-run this
script and commit the result to fix it.
"""
import json
from pathlib import Path

from agentforge.schema.models import ProjectConfig

SCHEMA_PATH = Path("agentforge/schema/project.schema.json")


def main() -> None:
    schema = ProjectConfig.model_json_schema()
    SCHEMA_PATH.write_text(json.dumps(schema, indent=2) + "\n")
    print(f"Schema written to {SCHEMA_PATH}")


if __name__ == "__main__":
    main()
