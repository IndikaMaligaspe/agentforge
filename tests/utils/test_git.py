"""Tests for agentforge.utils.git."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agentforge.utils.git import init_repo


_PROJECT_PATH = Path("/fake/project")


def _make_completed_process(returncode: int) -> MagicMock:
    cp = MagicMock()
    cp.returncode = returncode
    return cp


class TestInitRepo:
    def test_success_returns_true(self):
        with patch("agentforge.utils.git.subprocess.run", return_value=_make_completed_process(0)) as mock_run:
            result = init_repo(_PROJECT_PATH)

        assert result is True

    def test_nonzero_exit_returns_false(self):
        with patch("agentforge.utils.git.subprocess.run", return_value=_make_completed_process(128)):
            result = init_repo(_PROJECT_PATH)

        assert result is False

    def test_file_not_found_returns_false(self):
        with patch("agentforge.utils.git.subprocess.run", side_effect=FileNotFoundError):
            result = init_repo(_PROJECT_PATH)

        assert result is False

    def test_correct_cwd_passed(self):
        with patch("agentforge.utils.git.subprocess.run", return_value=_make_completed_process(0)) as mock_run:
            init_repo(_PROJECT_PATH)

        mock_run.assert_called_once_with(
            ["git", "init"],
            cwd=_PROJECT_PATH,
            check=False,
            capture_output=True,
        )
