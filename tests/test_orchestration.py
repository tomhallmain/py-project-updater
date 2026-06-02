"""Tests for SubprojectManager Phase 3 + 4 behaviour: backup writing, main project abort, CLI flags."""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from py_project_updater.models.subproject import SubprojectInfo
from py_project_updater.orchestration import SubprojectManager


def _manager(tmp_path, recovery_dir=None, test_mode=False, **kwargs):
    env = tmp_path / "venv"
    env.mkdir(exist_ok=True)
    return SubprojectManager(
        root_path=tmp_path,
        env_path=env,
        test_mode=test_mode,
        recovery_dir=recovery_dir or tmp_path / "recovery",
        **kwargs,
    )


def _subproject(tmp_path, name="mysub"):
    return SubprojectInfo(
        path=tmp_path / name,
        requirements_file=None,
        name=name,
        github_url="https://github.com/test/mysub.git",
    )


# ---------------------------------------------------------------------------
# _save_stash_backup
# ---------------------------------------------------------------------------

class TestSaveStashBackup:

    def test_creates_patch_and_info_files(self, tmp_path):
        manager = _manager(tmp_path)
        sub = _subproject(tmp_path)
        diff = "diff --git a/foo.py b/foo.py\n--- a/foo.py\n+++ b/foo.py\n"

        result = manager._save_stash_backup(sub, diff)

        assert result is not None
        assert result.suffix == ".patch"
        assert result.read_text(encoding="utf-8") == diff
        info = (result.parent / "stash_info.txt").read_text(encoding="utf-8")
        assert "mysub" in info
        assert "git apply" in info

    def test_creates_recovery_dir_if_absent(self, tmp_path):
        recovery = tmp_path / "not_yet_created"
        manager = _manager(tmp_path, recovery_dir=recovery)
        sub = _subproject(tmp_path)

        manager._save_stash_backup(sub, "diff content")

        assert recovery.exists()
        assert (recovery / "mysub").is_dir()

    def test_patch_filename_contains_timestamp(self, tmp_path):
        manager = _manager(tmp_path)
        sub = _subproject(tmp_path)

        result = manager._save_stash_backup(sub, "diff")

        # Filename is stash_YYYYMMDD_HHMMSS.patch
        assert result is not None
        stem = result.stem  # e.g. stash_20260602_153000
        parts = stem.split("_")
        assert parts[0] == "stash"
        assert len(parts[1]) == 8   # YYYYMMDD
        assert len(parts[2]) == 6   # HHMMSS

    def test_returns_none_on_permission_error(self, tmp_path):
        if sys.platform == "win32":
            pytest.skip("chmod not reliable on Windows")
        recovery = tmp_path / "recovery"
        recovery.mkdir()
        recovery.chmod(0o444)
        try:
            manager = _manager(tmp_path, recovery_dir=recovery)
            sub = _subproject(tmp_path)
            result = manager._save_stash_backup(sub, "diff")
            assert result is None
        finally:
            recovery.chmod(0o755)

    def test_github_url_included_in_info(self, tmp_path):
        manager = _manager(tmp_path)
        sub = _subproject(tmp_path)

        result = manager._save_stash_backup(sub, "diff")

        info = (result.parent / "stash_info.txt").read_text(encoding="utf-8")
        assert "https://github.com/test/mysub.git" in info

    def test_unknown_github_url_shows_placeholder(self, tmp_path):
        manager = _manager(tmp_path)
        sub = SubprojectInfo(path=tmp_path / "sub", requirements_file=None, name="sub")

        result = manager._save_stash_backup(sub, "diff")

        info = (result.parent / "stash_info.txt").read_text(encoding="utf-8")
        assert "unknown" in info


# ---------------------------------------------------------------------------
# Main project abort check
# ---------------------------------------------------------------------------

class TestMainProjectAbort:

    def _patched_manager(self, tmp_path, *, git_status, volume_check):
        manager = _manager(tmp_path, test_mode=False)
        main_sub = SubprojectInfo(
            path=tmp_path, requirements_file=None, name=tmp_path.name
        )
        with patch(
            "py_project_updater.orchestration.SubprojectFinder.find_subprojects",
            return_value=[main_sub],
        ), patch.object(
            manager.git_manager, "get_git_status", return_value=git_status
        ), patch.object(
            manager.git_manager, "check_change_volume", return_value=volume_check
        ), patch.object(
            manager.git_manager, "get_remote_url", return_value=None
        ), patch.object(
            manager.git_manager, "update_repository",
            return_value=(True, "Repository up to date", None),
        ), patch(
            "py_project_updater.orchestration.GitCommitChecker.get_last_commit_date",
            return_value=None,
        ):
            yield manager

    def test_dirty_main_exceeds_limit_raises_before_processing(self, tmp_path):
        manager = _manager(tmp_path, test_mode=False)
        main_sub = SubprojectInfo(path=tmp_path, requirements_file=None, name=tmp_path.name)

        with patch(
            "py_project_updater.orchestration.SubprojectFinder.find_subprojects",
            return_value=[main_sub],
        ), patch.object(
            manager.git_manager, "get_git_status",
            return_value=(False, "Repository has uncommitted changes", False),
        ), patch.object(
            manager.git_manager, "check_change_volume",
            return_value=(False, "50% of files changed"),
        ):
            with pytest.raises(RuntimeError, match="safe stashing limits"):
                manager.process_subprojects()

    def test_dirty_main_within_limits_does_not_abort(self, tmp_path):
        manager = _manager(tmp_path, test_mode=False)
        main_sub = SubprojectInfo(path=tmp_path, requirements_file=None, name=tmp_path.name)

        with patch(
            "py_project_updater.orchestration.SubprojectFinder.find_subprojects",
            return_value=[main_sub],
        ), patch.object(
            manager.git_manager, "get_git_status",
            return_value=(False, "Repository has uncommitted changes", False),
        ), patch.object(
            manager.git_manager, "check_change_volume",
            return_value=(True, ""),
        ), patch.object(
            manager.git_manager, "get_remote_url", return_value=None,
        ), patch.object(
            manager.git_manager, "update_repository",
            return_value=(True, "Repository up to date", None),
        ), patch(
            "py_project_updater.orchestration.GitCommitChecker.get_last_commit_date",
            return_value=None,
        ):
            # Should not raise
            manager.process_subprojects()

    def test_clean_main_does_not_abort(self, tmp_path):
        manager = _manager(tmp_path, test_mode=False)
        main_sub = SubprojectInfo(path=tmp_path, requirements_file=None, name=tmp_path.name)

        with patch(
            "py_project_updater.orchestration.SubprojectFinder.find_subprojects",
            return_value=[main_sub],
        ), patch.object(
            manager.git_manager, "get_git_status",
            return_value=(True, "Repository is clean", False),
        ), patch.object(
            manager.git_manager, "get_remote_url", return_value=None,
        ), patch.object(
            manager.git_manager, "update_repository",
            return_value=(True, "Repository up to date", None),
        ), patch(
            "py_project_updater.orchestration.GitCommitChecker.get_last_commit_date",
            return_value=None,
        ):
            manager.process_subprojects()

    def test_test_mode_skips_abort_even_if_volume_exceeded(self, tmp_path):
        manager = _manager(tmp_path, test_mode=True)
        main_sub = SubprojectInfo(path=tmp_path, requirements_file=None, name=tmp_path.name)

        with patch(
            "py_project_updater.orchestration.SubprojectFinder.find_subprojects",
            return_value=[main_sub],
        ), patch.object(
            manager.git_manager, "check_change_volume",
            return_value=(False, "too many files"),
        ), patch(
            "py_project_updater.orchestration.GitCommitChecker.get_last_commit_date",
            return_value=None,
        ):
            # No RuntimeError — test mode bypasses the abort
            manager.process_subprojects()


# ---------------------------------------------------------------------------
# stash_diff wiring — backup is saved when update_repository returns a diff
# ---------------------------------------------------------------------------

class TestStashDiffWiring:

    def test_backup_saved_when_pop_fails(self, tmp_path):
        manager = _manager(tmp_path, test_mode=False)
        sub = SubprojectInfo(path=tmp_path / "sub", requirements_file=None, name="sub")
        fake_diff = "diff --git a/foo.py b/foo.py\n"

        with patch.object(
            manager.git_manager, "is_git_repo", return_value=True
        ), patch.object(
            manager.git_manager, "get_remote_url", return_value=None
        ), patch.object(
            manager.git_manager, "get_git_status",
            return_value=(False, "Repository has uncommitted changes", False),
        ), patch.object(
            manager.git_manager, "update_repository",
            return_value=(False, "Pulled but stash pop failed", fake_diff),
        ), patch.object(
            manager, "_save_stash_backup", wraps=manager._save_stash_backup
        ) as mock_backup, patch(
            "py_project_updater.orchestration.GitCommitChecker.get_last_commit_date",
            return_value=None,
        ):
            manager.process_subproject(sub)

        mock_backup.assert_called_once_with(sub, fake_diff)

    def test_no_backup_when_pop_succeeds(self, tmp_path):
        manager = _manager(tmp_path, test_mode=False)
        sub = SubprojectInfo(path=tmp_path / "sub", requirements_file=None, name="sub")

        with patch.object(
            manager.git_manager, "is_git_repo", return_value=True
        ), patch.object(
            manager.git_manager, "get_remote_url", return_value=None
        ), patch.object(
            manager.git_manager, "get_git_status",
            return_value=(True, "Repository is clean", False),
        ), patch.object(
            manager.git_manager, "update_repository",
            return_value=(True, "Repository up to date", None),
        ), patch.object(
            manager, "_save_stash_backup"
        ) as mock_backup, patch(
            "py_project_updater.orchestration.GitCommitChecker.get_last_commit_date",
            return_value=None,
        ):
            manager.process_subproject(sub)

        mock_backup.assert_not_called()


# ---------------------------------------------------------------------------
# Phase 4 — CLI flag defaults passed through to SubprojectManager
# ---------------------------------------------------------------------------

class TestCLIFlagDefaults:
    """Verify that the three new flags reach SubprojectManager with correct defaults."""

    def _parse(self, extra_args=None):
        """Run the parser with required args plus any extras, return namespace."""
        from py_project_updater.cli import _make_parser
        base = ["--root-path", "/tmp/root", "--env-path", "/tmp/venv"]
        return _make_parser().parse_args(base + (extra_args or []))

    def test_default_recovery_dir(self):
        from py_project_updater.config import DEFAULT_RECOVERY_DIR
        args = self._parse()
        assert args.recovery_dir == DEFAULT_RECOVERY_DIR

    def test_custom_recovery_dir(self, tmp_path):
        args = self._parse(["--recovery-dir", str(tmp_path / "my_recovery")])
        assert args.recovery_dir == tmp_path / "my_recovery"

    def test_default_stash_file_threshold(self):
        from py_project_updater.config import DEFAULT_STASH_FILE_THRESHOLD
        args = self._parse()
        assert args.stash_file_threshold == DEFAULT_STASH_FILE_THRESHOLD

    def test_custom_stash_file_threshold(self):
        args = self._parse(["--stash-file-threshold", "0.25"])
        assert args.stash_file_threshold == pytest.approx(0.25)

    def test_default_stash_line_threshold(self):
        from py_project_updater.config import DEFAULT_STASH_LINE_THRESHOLD
        args = self._parse()
        assert args.stash_line_threshold == DEFAULT_STASH_LINE_THRESHOLD

    def test_custom_stash_line_threshold(self):
        args = self._parse(["--stash-line-threshold", "300"])
        assert args.stash_line_threshold == 300

    def test_flags_reach_subproject_manager(self, tmp_path):
        env = tmp_path / "venv"
        env.mkdir()
        recovery = tmp_path / "my_recovery"
        manager = SubprojectManager(
            root_path=tmp_path,
            env_path=env,
            stash_file_threshold=0.25,
            stash_line_threshold=300,
            recovery_dir=recovery,
        )
        assert manager.stash_file_threshold == pytest.approx(0.25)
        assert manager.stash_line_threshold == 300
        assert manager.recovery_dir == recovery
