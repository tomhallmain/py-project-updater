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


class TestCheckChangeVolume:
    """Tests for GitManager.check_change_volume."""

    def _gm(self):
        return GitManager(reporter=RunReporter(enabled=False))

    def _run(self, numstat_stdout="", ls_stdout="", numstat_rc=0, ls_rc=0):
        return [
            _make_run(numstat_rc, numstat_stdout),
            _make_run(ls_rc, ls_stdout),
        ]

    def test_within_both_limits(self, tmp_root):
        gm = self._gm()
        with patch("py_project_updater.services.git.subprocess.run") as run:
            run.side_effect = self._run(
                numstat_stdout="5\t3\tfoo.py\n",
                ls_stdout="\n".join(f"f{i}.py" for i in range(20)),
            )
            ok, reason = gm.check_change_volume(tmp_root, file_threshold=0.10, line_threshold=150)
        assert ok is True
        assert reason == ""

    def test_file_ratio_exceeded(self, tmp_root):
        gm = self._gm()
        # 3 changed out of 10 total = 30% > 10%
        with patch("py_project_updater.services.git.subprocess.run") as run:
            run.side_effect = self._run(
                numstat_stdout="1\t1\ta.py\n1\t1\tb.py\n1\t1\tc.py\n",
                ls_stdout="\n".join(f"f{i}.py" for i in range(10)),
            )
            ok, reason = gm.check_change_volume(tmp_root, file_threshold=0.10, line_threshold=150)
        assert ok is False
        assert "file threshold" in reason

    def test_single_file_line_limit_exceeded(self, tmp_root):
        gm = self._gm()
        # 1 changed out of 100 = 1% (fine), but 200 lines changed (exceeds 150)
        with patch("py_project_updater.services.git.subprocess.run") as run:
            run.side_effect = self._run(
                numstat_stdout="120\t80\tbig.py\n",
                ls_stdout="\n".join(f"f{i}.py" for i in range(100)),
            )
            ok, reason = gm.check_change_volume(tmp_root, file_threshold=0.10, line_threshold=150)
        assert ok is False
        assert "line threshold" in reason
        assert "big.py" in reason

    def test_binary_files_excluded_from_line_count(self, tmp_root):
        gm = self._gm()
        # binary file ('-\t-') + small text file; 2 of 20 = 10% (exactly at threshold, not over)
        with patch("py_project_updater.services.git.subprocess.run") as run:
            run.side_effect = self._run(
                numstat_stdout="-\t-\timage.png\n10\t5\tfoo.py\n",
                ls_stdout="\n".join(f"f{i}.py" for i in range(20)),
            )
            ok, reason = gm.check_change_volume(tmp_root, file_threshold=0.10, line_threshold=150)
        # 2/20 = 10% which is NOT > 10%, so passes
        assert ok is True

    def test_no_changes_returns_true(self, tmp_root):
        gm = self._gm()
        with patch("py_project_updater.services.git.subprocess.run") as run:
            run.side_effect = self._run(
                numstat_stdout="",
                ls_stdout="\n".join(f"f{i}.py" for i in range(20)),
            )
            ok, _ = gm.check_change_volume(tmp_root)
        assert ok is True

    def test_numstat_failure_returns_false(self, tmp_root):
        gm = self._gm()
        with patch("py_project_updater.services.git.subprocess.run") as run:
            run.side_effect = self._run(numstat_rc=1, numstat_stdout="", ls_stdout="")
            ok, reason = gm.check_change_volume(tmp_root)
        assert ok is False
        assert "Could not measure" in reason

    def test_subprocess_exception_returns_false(self, tmp_root):
        gm = self._gm()
        with patch("py_project_updater.services.git.subprocess.run", side_effect=OSError("boom")):
            ok, reason = gm.check_change_volume(tmp_root)
        assert ok is False
        assert "boom" in reason


class TestUpdateRepositoryDirtyFlow:
    """Tests for the new stash/pull/pop path in update_repository."""

    def _gm(self):
        return GitManager(reporter=RunReporter(enabled=False))

    def _dirty_status(self):
        return (False, "Repository has uncommitted changes", False)

    def _clean_status(self):
        return (True, "Repository is clean", False)

    def test_test_mode_dirty_logs_stash_message(self, tmp_root, test_mode_manager):
        gm = GitManager(reporter=test_mode_manager)
        ok, msg, diff = gm.update_repository(tmp_root, status=self._dirty_status())
        assert ok is True
        assert "stash" in msg.lower()
        assert diff is None
        assert any("stash" in (op.command or "") for op in test_mode_manager.operations)

    def test_volume_exceeded_falls_back_to_fetch(self, tmp_root):
        gm = self._gm()
        # Patch check_change_volume to fail, then fetch to succeed
        with patch.object(gm, "check_change_volume", return_value=(False, "too many files")), \
             patch("py_project_updater.services.git.subprocess.run") as run:
            run.return_value = _make_run(0, "")
            ok, msg, diff = gm.update_repository(tmp_root, status=self._dirty_status())
        assert ok is True
        assert "fetch" in msg.lower()
        assert diff is None

    def test_stash_succeeds_pull_succeeds_pop_succeeds(self, tmp_root):
        gm = self._gm()
        with patch.object(gm, "check_change_volume", return_value=(True, "")), \
             patch.object(gm, "stash_changes", return_value=(True, "stash@{0}")), \
             patch.object(gm, "pop_stash", return_value=(True, "")), \
             patch("py_project_updater.services.git.subprocess.run") as run:
            run.return_value = _make_run(0, "Fast-forward")
            ok, msg, diff = gm.update_repository(tmp_root, status=self._dirty_status())
        assert ok is True
        assert "restored" in msg.lower()
        assert diff is None

    def test_nothing_to_stash_pulls_directly(self, tmp_root):
        gm = self._gm()
        with patch.object(gm, "check_change_volume", return_value=(True, "")), \
             patch.object(gm, "stash_changes", return_value=(False, "nothing to stash")), \
             patch("py_project_updater.services.git.subprocess.run") as run:
            run.return_value = _make_run(0, "Already up to date.")
            ok, msg, diff = gm.update_repository(tmp_root, status=self._dirty_status())
        assert ok is True
        assert diff is None

    def test_stash_fails_falls_back_to_fetch(self, tmp_root):
        gm = self._gm()
        with patch.object(gm, "check_change_volume", return_value=(True, "")), \
             patch.object(gm, "stash_changes", return_value=(False, "some other error")), \
             patch("py_project_updater.services.git.subprocess.run") as run:
            run.return_value = _make_run(0, "")
            ok, msg, diff = gm.update_repository(tmp_root, status=self._dirty_status())
        assert ok is True
        assert "fetch" in msg.lower()
        assert diff is None

    def test_pull_fails_after_stash_restores_and_returns_error(self, tmp_root):
        gm = self._gm()
        pop_called = []
        with patch.object(gm, "check_change_volume", return_value=(True, "")), \
             patch.object(gm, "stash_changes", return_value=(True, "stash@{0}")), \
             patch.object(gm, "pop_stash", side_effect=lambda p: pop_called.append(p) or (True, "")), \
             patch("py_project_updater.services.git.subprocess.run") as run:
            run.return_value = _make_run(1, "", "fatal: no remote")
            ok, msg, diff = gm.update_repository(tmp_root, status=self._dirty_status())
        assert ok is False
        assert "pull" in msg.lower()
        assert len(pop_called) == 1  # pop was called to restore
        assert diff is None

    def test_pop_fails_exports_diff_and_cleans_up(self, tmp_root):
        gm = self._gm()
        fake_diff = "diff --git a/foo.py b/foo.py\n--- a/foo.py\n+++ b/foo.py\n"
        with patch.object(gm, "check_change_volume", return_value=(True, "")), \
             patch.object(gm, "stash_changes", return_value=(True, "stash@{0}")), \
             patch.object(gm, "pop_stash", return_value=(False, "CONFLICT in foo.py")), \
             patch.object(gm, "export_stash", return_value=fake_diff), \
             patch.object(gm, "drop_stash", return_value=True), \
             patch("py_project_updater.services.git.subprocess.run") as run:
            run.return_value = _make_run(0, "Fast-forward")
            ok, msg, diff = gm.update_repository(tmp_root, status=self._dirty_status())
        assert ok is False
        assert "recovery" in msg.lower()
        assert diff == fake_diff

    def test_clean_repo_still_pulls(self, tmp_root):
        gm = self._gm()
        with patch("py_project_updater.services.git.subprocess.run") as run:
            # get_git_status (is_clean_after check) makes two calls:
            #   1. git status --porcelain  → empty (clean)
            #   2. git cherry -v           → empty (no unpushed commits)
            # Then: git pull
            run.side_effect = [
                _make_run(0, ""),                           # git status --porcelain
                _make_run(0, ""),                           # git cherry -v
                _make_run(0, "Fast-forward\n1 file changed"),  # git pull
            ]
            ok, msg, diff = gm.update_repository(tmp_root, status=(True, "Repository is clean", False))
        assert ok is True
        assert diff is None


class TestGitManagerIgnorePatterns:
    """Tests for PYTHON_IGNORE_PATTERNS."""

    def test_ignore_patterns_defined(self):
        assert hasattr(GitManager, "PYTHON_IGNORE_PATTERNS")
        patterns = GitManager.PYTHON_IGNORE_PATTERNS
        assert "__pycache__/" in patterns
        assert "*.pyc" in patterns
