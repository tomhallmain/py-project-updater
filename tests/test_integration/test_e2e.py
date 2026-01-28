"""Optional integration tests: real filesystem, test-mode run.

These tests use temporary directories and (when test_mode=True) do not
run real git or pip. They verify that SubprojectManager.run() completes
and produces a summary. For full e2e with real git/pip, run on a host
that has them and skip when unavailable.
"""

from pathlib import Path

import pytest

from py_project_updater.orchestration import SubprojectManager


class TestSubprojectManagerE2E:
    """Minimal integration tests for SubprojectManager."""

    def test_run_with_empty_root_produces_summary(self, tmp_root: Path):
        """On an empty root, run() completes and prints Test Mode Summary."""
        env_path = tmp_root / "venv"
        env_path.mkdir()
        manager = SubprojectManager(
            root_path=tmp_root,
            env_path=env_path,
            test_mode=True,
            max_depth=2,
        )
        # run() calls process_subprojects then print(get_summary())
        manager.run()
        # If we get here without exception, the run completed
        assert len(manager.test_mode.subprojects) == 0

    def test_run_with_one_subproject_logs_operations(self, tmp_root: Path):
        """With one subproject (requirements.txt + .git), run() discovers it and logs."""
        sub = tmp_root / "sub"
        sub.mkdir()
        (sub / "requirements.txt").write_text("requests>=2.0\n", encoding="utf-8")
        (sub / ".git").mkdir()
        env_path = tmp_root / "venv"
        env_path.mkdir()
        manager = SubprojectManager(
            root_path=tmp_root,
            env_path=env_path,
            test_mode=True,
            max_depth=2,
        )
        manager.run()
        assert len(manager.test_mode.subprojects) >= 1
        assert any(s.name == "sub" for s in manager.test_mode.subprojects)
        # In test mode, git/pip are not run but operations are logged
        assert len(manager.test_mode.operations) >= 1
