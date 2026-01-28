"""Pip installation in the project virtual environment."""

import os
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from py_project_updater.reporting import TestModeManager


class PipInstaller:
    """Handles pip installation in the correct virtual environment."""

    def __init__(self, test_mode: TestModeManager):
        self.test_mode = test_mode

    def _pip_path(self, env_path: Path) -> str:
        """Return path to pip executable for the given environment."""
        if os.name == "nt":
            return str(env_path / "Scripts" / "pip")
        return str(env_path / "bin" / "pip")

    def install_requirements(
        self, requirements_file: Path, env_path: Path
    ) -> Tuple[bool, Optional[str]]:
        """Install packages from a requirements.txt file.

        Returns:
            Tuple[bool, Optional[str]]: (success, error_message)
            success is True if the packages were installed or already satisfied
            error_message is None if successful, or contains the error message if failed
        """
        pip_cmd = [
            self._pip_path(env_path),
            "install",
            "-r",
            str(requirements_file),
        ]

        if self.test_mode.enabled:
            self.test_mode.log_operation(
                True,
                f"Would install requirements from {requirements_file}",
                " ".join(pip_cmd),
                [f"Install requirements from {requirements_file}"],
            )
            return True, None

        try:
            result = subprocess.run(pip_cmd, capture_output=True, text=True)

            if result.returncode == 0:
                return True, None

            stderr = (result.stderr or "").lower()
            if any(
                w in stderr
                for w in [
                    "already satisfied",
                    "requirement already satisfied",
                    "dependency conflict",
                    "conflicting dependencies",
                    "version conflict",
                    "incompatible dependencies",
                ]
            ):
                return True, None

            return False, (result.stderr or "").strip()

        except Exception as e:
            return False, str(e)

    def install_package(
        self, package: str, version: Optional[str], env_path: Path
    ) -> Tuple[bool, Optional[str]]:
        """Install a single package in the specified virtual environment.

        This is used when installing packages from subproject requirements
        (per-package rather than -r requirements.txt).

        Returns:
            Tuple[bool, Optional[str]]: (success, error_message)
            success is True if the package was installed or already satisfied
            error_message is None if successful, or contains the error message if failed
        """
        pip_exe = self._pip_path(env_path)
        spec = f"{package}=={version}" if version else package
        pip_cmd = [pip_exe, "install", spec]

        if self.test_mode.enabled:
            self.test_mode.log_operation(
                True,
                f"Would install package: {package}{'==' + version if version else ''}",
                " ".join(pip_cmd),
                [f"Install {package} in virtual environment"],
            )
            return True, None

        try:
            result = subprocess.run(pip_cmd, capture_output=True, text=True)

            if result.returncode == 0:
                return True, None

            stderr = (result.stderr or "").lower()
            if any(
                w in stderr
                for w in [
                    "already satisfied",
                    "requirement already satisfied",
                    "dependency conflict",
                    "conflicting dependencies",
                    "version conflict",
                    "incompatible dependencies",
                ]
            ):
                return True, None

            return False, (result.stderr or "").strip()

        except Exception as e:
            return False, str(e)
