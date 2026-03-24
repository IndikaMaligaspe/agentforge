"""
Tests for the project.yaml loader.
"""
import os
from pathlib import Path
import pytest
from pydantic import ValidationError

from agentforge.schema.loader import load, dump
from agentforge.schema.models import ProjectConfig

FIXTURES_DIR = Path(__file__).parent / "fixtures"

def test_load_minimal():
    """Test loading a minimal valid project.yaml."""
    config = load(FIXTURES_DIR / "minimal.yaml")
    assert isinstance(config, ProjectConfig)
    assert config.metadata.name == "minimal_project"
    assert len(config.agents) == 1
    assert config.agents[0].key == "sql"

def test_load_full():
    """Test loading a full-featured project.yaml."""
    config = load(FIXTURES_DIR / "full.yaml")
    assert isinstance(config, ProjectConfig)
    assert config.metadata.name == "full_featured_project"
    assert len(config.agents) == 2
    assert config.agents[0].key == "sql"
    assert config.agents[1].key == "analytics"
    assert len(config.agents[0].tools) == 2
    assert config.database.tables == ["users", "orders", "products", "categories"]
    assert config.api.query_max_length == 5000
    assert config.security.enable_auth is True

def test_load_nonexistent():
    """Test loading a nonexistent file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load(FIXTURES_DIR / "nonexistent.yaml")

def test_dump_and_load(tmp_path):
    """Test round-trip dump and load."""
    original = load(FIXTURES_DIR / "minimal.yaml")
    
    # Dump to a temporary file
    temp_file = tmp_path / "test_dump.yaml"
    dump(original, temp_file)
    
    # Load it back
    reloaded = load(temp_file)
    
    # Compare
    assert reloaded.metadata.name == original.metadata.name
    assert len(reloaded.agents) == len(original.agents)
    assert reloaded.agents[0].key == original.agents[0].key
    assert reloaded.workflow.default_intent == original.workflow.default_intent