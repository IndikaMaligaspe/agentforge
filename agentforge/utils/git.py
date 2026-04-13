"""Git utilities for agentforge."""

import subprocess
from pathlib import Path


def init_repo(project_path: Path) -> bool:
    """Run ``git init`` in *project_path*.

    Returns True only when the command exits with returncode 0.
    Returns False if the ``git`` binary is not on PATH or the command fails.
    Never stages files or creates a commit.
    """
    try:
        result = subprocess.run(
            ["git", "init"],
            cwd=project_path,
            check=False,
            capture_output=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False
