"""Tests for PipInstaller (test mode and mocked subprocess)."""

import os
from pathlib import Path

import pytest

from py_project_updater.reporting import TestModeManager
from py_project_updater.services.pip_installer import PipInstaller


class TestPipInstallerTestMode:
    """Tests when test mode is enabled (no real pip calls)."""

    def test_install_requirements_succeeds_in_test_mode(
        self, tmp_root: Path, test_mode_manager: TestModeManager
    ):
        req_file = tmp_root / "requirements.txt"
        req_file.write_text("requests==2.28.0\n", encoding="utf-8")
        env_path = tmp_root / "venv"
        env_path.mkdir()

        installer = PipInstaller(test_mode=test_mode_manager)
        success, err = installer.install_requirements(req_file, env_path)
        assert success is True
        assert err is None
        assert len(test_mode_manager.operations) == 1
        assert "install" in (test_mode_manager.operations[0].command or "").lower()
        assert "requirements" in (test_mode_manager.operations[0].message or "").lower()

    def test_install_package_succeeds_in_test_mode(
        self, tmp_root: Path, test_mode_manager: TestModeManager
    ):
        env_path = tmp_root / "venv"
        env_path.mkdir()

        installer = PipInstaller(test_mode=test_mode_manager)
        success, err = installer.install_package("requests", "2.28.0", env_path)
        assert success is True
        assert err is None
        assert len(test_mode_manager.operations) == 1
        assert "2.28.0" in (test_mode_manager.operations[0].message or "")


class TestPipInstallerPipPath:
    """Tests for _pip_path behaviour."""

    def test_pip_path_contains_scripts_or_bin_and_pip(self):
        installer = PipInstaller(test_mode=TestModeManager(enabled=True))
        env = Path("C:/venv")
        path = installer._pip_path(env)
        if os.name == "nt":
            assert "Scripts" in path
        else:
            assert "bin" in path
        assert "pip" in path
