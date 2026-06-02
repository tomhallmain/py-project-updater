"""Tests for GitManager (with test mode and mocked subprocess)."""

from pathlib import Path
from unittest.mock import patch

import pytest

from py_project_updater.reporting import RunReporter
from py_project_updater.services.git import GitManager


class TestGitManagerTestMode:
    """Tests when test mode is enabled (no real subprocess calls)."""

    def test_is_git_repo_returns_true_in_test_mode(self, tmp_root: Path, test_mode_manager: RunReporter):
        gm = GitManager(reporter=test_mode_manager)
        assert gm.is_git_repo(tmp_root) is True
        assert len(test_mode_manager.operations) == 1
        assert "rev-parse" in (test_mode_manager.operations[0].command or "")

    def test_get_remote_url_returns_fake_in_test_mode(self, tmp_root: Path, test_mode_manager: RunReporter):
        gm = GitManager(reporter=test_mode_manager)
        url = gm.get_remote_url(tmp_root)
        assert url is not None
        assert "github.com" in url
        assert url.endswith(".git")
        assert len(test_mode_manager.operations) == 1
        assert "remote get-url" in (test_mode_manager.operations[0].command or "")


class TestGitManagerWithMockedSubprocess:
    """Tests with subprocess.run mocked for non-test-mode paths."""

    def test_is_git_repo_true_when_git_says_true(self, tmp_root: Path):
        test_mode = RunReporter(enabled=False)
        gm = GitManager(reporter=test_mode)
        with patch("py_project_updater.services.git.subprocess.run") as run:
            run.return_value = type("R", (), {"returncode": 0, "stdout": "true", "stderr": ""})()
            assert gm.is_git_repo(tmp_root) is True
            run.assert_called_once()
            assert "rev-parse" in run.call_args[0][0]

    def test_is_git_repo_false_when_git_says_false(self, tmp_root: Path):
        test_mode = RunReporter(enabled=False)
        gm = GitManager(reporter=test_mode)
        with patch("py_project_updater.services.git.subprocess.run") as run:
            run.return_value = type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})()
            assert gm.is_git_repo(tmp_root) is False

    def test_get_remote_url_returns_https_converted_from_ssh(self, tmp_root: Path):
        test_mode = RunReporter(enabled=False)
        gm = GitManager(reporter=test_mode)
        with patch("py_project_updater.services.git.subprocess.run") as run:
            run.return_value = type(
                "R", (), {"returncode": 0, "stdout": "git@github.com:user/repo.git\n", "stderr": ""}
            )()
            url = gm.get_remote_url(tmp_root)
            assert url == "https://github.com/user/repo.git"

    def test_get_remote_url_returns_none_on_failure(self, tmp_root: Path):
        test_mode = RunReporter(enabled=False)
        gm = GitManager(reporter=test_mode)
        with patch("py_project_updater.services.git.subprocess.run") as run:
            run.return_value = type("R", (), {"returncode": 1, "stdout": "", "stderr": "error"})()
            assert gm.get_remote_url(tmp_root) is None


def _make_run(returncode=0, stdout="", stderr=""):
    """Build a minimal subprocess.run return value."""
    return type("R", (), {"returncode": returncode, "stdout": stdout, "stderr": stderr})()


class TestStashChanges:
    """Tests for GitManager.stash_changes."""

    def test_test_mode_logs_and_returns_ref(self, tmp_root: Path, test_mode_manager: RunReporter):
        gm = GitManager(reporter=test_mode_manager)
        ok, ref = gm.stash_changes(tmp_root)
        assert ok is True
        assert ref == "stash@{0}"
        assert any("stash" in (op.command or "") for op in test_mode_manager.operations)

    def test_success_returns_ref(self, tmp_root: Path):
        gm = GitManager(reporter=RunReporter(enabled=False))
        with patch("py_project_updater.services.git.subprocess.run") as run:
            run.return_value = _make_run(0, "Saved working directory and index state")
            ok, ref = gm.stash_changes(tmp_root)
        assert ok is True
        assert ref == "stash@{0}"

    def test_nothing_to_stash_detected(self, tmp_root: Path):
        gm = GitManager(reporter=RunReporter(enabled=False))
        with patch("py_project_updater.services.git.subprocess.run") as run:
            run.return_value = _make_run(0, "No local changes to save")
            ok, reason = gm.stash_changes(tmp_root)
        assert ok is False
        assert reason == "nothing to stash"

    def test_git_failure_returns_stderr(self, tmp_root: Path):
        gm = GitManager(reporter=RunReporter(enabled=False))
        with patch("py_project_updater.services.git.subprocess.run") as run:
            run.return_value = _make_run(1, "", "fatal: not a git repo")
            ok, msg = gm.stash_changes(tmp_root)
        assert ok is False
        assert "not a git repo" in msg

    def test_subprocess_exception_returns_false(self, tmp_root: Path):
        gm = GitManager(reporter=RunReporter(enabled=False))
        with patch("py_project_updater.services.git.subprocess.run", side_effect=OSError("boom")):
            ok, msg = gm.stash_changes(tmp_root)
        assert ok is False
        assert "boom" in msg


class TestPopStash:
    """Tests for GitManager.pop_stash."""

    def test_test_mode_logs_and_returns_success(self, tmp_root: Path, test_mode_manager: RunReporter):
        gm = GitManager(reporter=test_mode_manager)
        ok, msg = gm.pop_stash(tmp_root)
        assert ok is True
        assert msg == ""
        assert any("stash pop" in (op.command or "") for op in test_mode_manager.operations)

    def test_success_returns_empty_message(self, tmp_root: Path):
        gm = GitManager(reporter=RunReporter(enabled=False))
        with patch("py_project_updater.services.git.subprocess.run") as run:
            run.return_value = _make_run(0, "")
            ok, msg = gm.pop_stash(tmp_root)
        assert ok is True
        assert msg == ""

    def test_conflict_returns_false_with_output(self, tmp_root: Path):
        gm = GitManager(reporter=RunReporter(enabled=False))
        with patch("py_project_updater.services.git.subprocess.run") as run:
            run.return_value = _make_run(1, "CONFLICT (content): Merge conflict in foo.py", "")
            ok, msg = gm.pop_stash(tmp_root)
        assert ok is False
        assert "CONFLICT" in msg

    def test_subprocess_exception_returns_false(self, tmp_root: Path):
        gm = GitManager(reporter=RunReporter(enabled=False))
        with patch("py_project_updater.services.git.subprocess.run", side_effect=OSError("boom")):
            ok, msg = gm.pop_stash(tmp_root)
        assert ok is False
        assert "boom" in msg


class TestExportStash:
    """Tests for GitManager.export_stash."""

    def test_returns_diff_on_success(self, tmp_root: Path):
        gm = GitManager(reporter=RunReporter(enabled=False))
        diff = "diff --git a/foo.py b/foo.py\n--- a/foo.py\n+++ b/foo.py\n"
        with patch("py_project_updater.services.git.subprocess.run") as run:
            run.return_value = _make_run(0, diff)
            result = gm.export_stash(tmp_root)
        assert result == diff

    def test_returns_none_on_empty_output(self, tmp_root: Path):
        gm = GitManager(reporter=RunReporter(enabled=False))
        with patch("py_project_updater.services.git.subprocess.run") as run:
            run.return_value = _make_run(0, "")
            result = gm.export_stash(tmp_root)
        assert result is None

    def test_returns_none_on_git_failure(self, tmp_root: Path):
        gm = GitManager(reporter=RunReporter(enabled=False))
        with patch("py_project_updater.services.git.subprocess.run") as run:
            run.return_value = _make_run(1, "", "error")
            result = gm.export_stash(tmp_root)
        assert result is None

    def test_returns_none_on_subprocess_exception(self, tmp_root: Path):
        gm = GitManager(reporter=RunReporter(enabled=False))
        with patch("py_project_updater.services.git.subprocess.run", side_effect=OSError):
            result = gm.export_stash(tmp_root)
        assert result is None


class TestDropStash:
    """Tests for GitManager.drop_stash."""

    def test_test_mode_logs_and_returns_true(self, tmp_root: Path, test_mode_manager: RunReporter):
        gm = GitManager(reporter=test_mode_manager)
        assert gm.drop_stash(tmp_root) is True
        assert any("stash drop" in (op.command or "") for op in test_mode_manager.operations)

    def test_success_returns_true(self, tmp_root: Path):
        gm = GitManager(reporter=RunReporter(enabled=False))
        with patch("py_project_updater.services.git.subprocess.run") as run:
            run.return_value = _make_run(0)
            assert gm.drop_stash(tmp_root) is True

    def test_failure_returns_false(self, tmp_root: Path):
        gm = GitManager(reporter=RunReporter(enabled=False))
        with patch("py_project_updater.services.git.subprocess.run") as run:
            run.return_value = _make_run(1)
            assert gm.drop_stash(tmp_root) is False


class TestGitManagerIgnorePatterns:
    """Tests for PYTHON_IGNORE_PATTERNS."""

    def test_ignore_patterns_defined(self):
        assert hasattr(GitManager, "PYTHON_IGNORE_PATTERNS")
        patterns = GitManager.PYTHON_IGNORE_PATTERNS
        assert "__pycache__/" in patterns
        assert "*.pyc" in patterns
