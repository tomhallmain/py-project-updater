"""Tests for GitManager (with test mode and mocked subprocess)."""

from pathlib import Path
from unittest.mock import patch

import pytest

from py_project_updater.reporting import TestModeManager
from py_project_updater.services.git import GitManager


class TestGitManagerTestMode:
    """Tests when test mode is enabled (no real subprocess calls)."""

    def test_is_git_repo_returns_true_in_test_mode(self, tmp_root: Path, test_mode_manager: TestModeManager):
        gm = GitManager(test_mode=test_mode_manager)
        assert gm.is_git_repo(tmp_root) is True
        assert len(test_mode_manager.operations) == 1
        assert "rev-parse" in (test_mode_manager.operations[0].command or "")

    def test_get_remote_url_returns_fake_in_test_mode(self, tmp_root: Path, test_mode_manager: TestModeManager):
        gm = GitManager(test_mode=test_mode_manager)
        url = gm.get_remote_url(tmp_root)
        assert url is not None
        assert "github.com" in url
        assert url.endswith(".git")
        assert len(test_mode_manager.operations) == 1
        assert "remote get-url" in (test_mode_manager.operations[0].command or "")


class TestGitManagerWithMockedSubprocess:
    """Tests with subprocess.run mocked for non-test-mode paths."""

    def test_is_git_repo_true_when_git_says_true(self, tmp_root: Path):
        test_mode = TestModeManager(enabled=False)
        gm = GitManager(test_mode=test_mode)
        with patch("py_project_updater.services.git.subprocess.run") as run:
            run.return_value = type("R", (), {"returncode": 0, "stdout": "true", "stderr": ""})()
            assert gm.is_git_repo(tmp_root) is True
            run.assert_called_once()
            assert "rev-parse" in run.call_args[0][0]

    def test_is_git_repo_false_when_git_says_false(self, tmp_root: Path):
        test_mode = TestModeManager(enabled=False)
        gm = GitManager(test_mode=test_mode)
        with patch("py_project_updater.services.git.subprocess.run") as run:
            run.return_value = type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})()
            assert gm.is_git_repo(tmp_root) is False

    def test_get_remote_url_returns_https_converted_from_ssh(self, tmp_root: Path):
        test_mode = TestModeManager(enabled=False)
        gm = GitManager(test_mode=test_mode)
        with patch("py_project_updater.services.git.subprocess.run") as run:
            run.return_value = type(
                "R", (), {"returncode": 0, "stdout": "git@github.com:user/repo.git\n", "stderr": ""}
            )()
            url = gm.get_remote_url(tmp_root)
            assert url == "https://github.com/user/repo.git"

    def test_get_remote_url_returns_none_on_failure(self, tmp_root: Path):
        test_mode = TestModeManager(enabled=False)
        gm = GitManager(test_mode=test_mode)
        with patch("py_project_updater.services.git.subprocess.run") as run:
            run.return_value = type("R", (), {"returncode": 1, "stdout": "", "stderr": "error"})()
            assert gm.get_remote_url(tmp_root) is None


class TestGitManagerIgnorePatterns:
    """Tests for PYTHON_IGNORE_PATTERNS."""

    def test_ignore_patterns_defined(self):
        assert hasattr(GitManager, "PYTHON_IGNORE_PATTERNS")
        patterns = GitManager.PYTHON_IGNORE_PATTERNS
        assert "__pycache__/" in patterns
        assert "*.pyc" in patterns
