"""
ScaffoldWriter — writes rendered template content to disk.

This module provides the ScaffoldWriter class, which is responsible for
writing rendered template content to the file system. It handles creating
the directory structure, writing files with proper encoding, and tracking
which files were written or skipped.

Responsibilities:
- Create directory tree automatically as needed
- Write files with UTF-8 encoding (with overwrite protection)
- Skip existing files unless overwrite is explicitly enabled
- Track written and skipped files for reporting
- Provide summary statistics of the write operation
"""
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ScaffoldWriter:
    """
    Writes rendered template content to the file system.
    
    This class handles writing rendered template content to files, creating
    directories as needed, and tracking which files were written or skipped.
    It provides protection against overwriting existing files unless explicitly
    enabled.
    
    Attributes:
        root: The root directory where files will be written
        overwrite: Whether to overwrite existing files (default: False)
        written: List of paths that were successfully written
        skipped: List of paths that were skipped (already exist)
    """
    root: Path
    overwrite: bool = False
    written: list[Path] = field(default_factory=list, init=False)
    skipped: list[Path] = field(default_factory=list, init=False)

    def write(self, relative_path: Path, content: str) -> None:
        """
        Write content to a file at the specified relative path.
        
        This method writes the given content to a file at the specified path
        relative to the root directory. It automatically creates any necessary
        parent directories. If the file already exists and overwrite is False,
        the file is skipped.
        
        Args:
            relative_path: Path relative to the root directory
            content: Text content to write to the file
            
        Note:
            The file is written with UTF-8 encoding.
            The method tracks written and skipped files internally.
        """
        target = self.root / relative_path
        if target.exists() and not self.overwrite:
            self.skipped.append(relative_path)
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self.written.append(relative_path)

    def summary(self) -> str:
        """
        Get a summary of the write operation.
        
        Returns:
            A string summarizing how many files were written and how many
            were skipped, with a hint about the --overwrite flag.
            
        Example:
            "5 files written, 2 skipped (use --overwrite to force)"
        """
        return (
            f"{len(self.written)} files written, "
            f"{len(self.skipped)} skipped (use --overwrite to force)"
        )