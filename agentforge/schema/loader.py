"""
Load and dump project.yaml using the ProjectConfig schema.

This module provides utility functions for reading and writing project.yaml
configuration files, with automatic validation against the Pydantic schema.
It serves as the bridge between the file system and the in-memory configuration
model used throughout agentforge.
"""
from pathlib import Path
import yaml
from .models import ProjectConfig

FILENAME = "project.yaml"

def load(path: Path = Path(FILENAME)) -> ProjectConfig:
    """
    Parse and validate a project.yaml file into a ProjectConfig object.

    This function reads the YAML file, parses it, and validates it against
    the ProjectConfig schema. If validation fails, a detailed ValidationError
    is raised with information about which fields failed validation and why.

    Args:
        path: Path to the project.yaml file (defaults to "project.yaml" in current directory)

    Returns:
        A validated ProjectConfig object

    Raises:
        FileNotFoundError: If the specified file doesn't exist
        ValidationError: If the YAML content doesn't match the ProjectConfig schema
        YAMLError: If the file contains invalid YAML syntax
    """
    raw = yaml.safe_load(path.read_text())
    return ProjectConfig.model_validate(raw)

def dump(config: ProjectConfig, path: Path = Path(FILENAME)) -> None:
    """
    Serialize a ProjectConfig object to a project.yaml file.

    This function converts the ProjectConfig to a dictionary and then
    writes it as YAML to the specified path. The serialization uses
    ``exclude_none=True`` so that optional v2 fields (entry, pattern,
    orchestrator, etc.) are omitted from legacy round-trips, preserving
    byte-clean backwards compatibility.

    Args:
        config: The ProjectConfig object to serialize
        path: Path where the YAML file should be written (defaults to "project.yaml")

    Raises:
        PermissionError: If the file cannot be written due to permissions
        IsADirectoryError: If the path points to a directory instead of a file
    """
    data = config.model_dump(mode="json", exclude_none=True)
    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
