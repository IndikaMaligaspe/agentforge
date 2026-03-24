"""
Tests for the scaffold writer.
"""
from pathlib import Path
import pytest

from agentforge.writer.scaffold import ScaffoldWriter

def test_write_new_file(tmp_path):
    """Test writing a new file."""
    writer = ScaffoldWriter(tmp_path)
    rel_path = Path("test_dir/test_file.txt")
    content = "Test content"
    
    writer.write(rel_path, content)
    
    # Check that the file was written
    assert (tmp_path / rel_path).exists()
    assert (tmp_path / rel_path).read_text() == content
    
    # Check that the file is in the written list
    assert rel_path in writer.written
    assert not writer.skipped

def test_write_existing_file_no_overwrite(tmp_path):
    """Test writing to an existing file with overwrite=False."""
    # Create the file first
    test_file = tmp_path / "existing.txt"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("Original content")
    
    writer = ScaffoldWriter(tmp_path, overwrite=False)
    rel_path = Path("existing.txt")
    new_content = "New content"
    
    writer.write(rel_path, new_content)
    
    # Check that the file was not overwritten
    assert test_file.read_text() == "Original content"
    
    # Check that the file is in the skipped list
    assert rel_path in writer.skipped
    assert not writer.written

def test_write_existing_file_with_overwrite(tmp_path):
    """Test writing to an existing file with overwrite=True."""
    # Create the file first
    test_file = tmp_path / "existing.txt"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("Original content")
    
    writer = ScaffoldWriter(tmp_path, overwrite=True)
    rel_path = Path("existing.txt")
    new_content = "New content"
    
    writer.write(rel_path, new_content)
    
    # Check that the file was overwritten
    assert test_file.read_text() == "New content"
    
    # Check that the file is in the written list
    assert rel_path in writer.written
    assert not writer.skipped

def test_summary():
    """Test the summary method."""
    writer = ScaffoldWriter(Path("/tmp"))
    writer.written = [Path("file1.txt"), Path("file2.txt")]
    writer.skipped = [Path("file3.txt")]
    
    summary = writer.summary()
    
    assert "2 files written" in summary
    assert "1 skipped" in summary