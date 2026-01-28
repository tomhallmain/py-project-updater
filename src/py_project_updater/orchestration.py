"""SubprojectManager: main orchestrator for subproject Git and pip operations."""

import logging
from pathlib import Path
from typing import List

from py_project_updater.models import SubprojectInfo
from py_project_updater.reporting import TestModeManager
from py_project_updater.services.finder import SubprojectFinder
from py_project_updater.services.github_commit import GitHubCommitChecker
from py_project_updater.services.git import GitManager
from py_project_updater.services.pip_installer import PipInstaller

logger = logging.getLogger(__name__)


class SubprojectManager:
    """Main orchestrator for managing subproject installations."""

    def __init__(
        self,
        root_path: Path,
        env_path: Path,
        test_mode: bool = False,
        git_only: bool = False,
        max_depth: int = 2,
    ):
        self.root_path = root_path
        self.env_path = env_path
        self.ignored_subprojects: set = set()
        self.test_mode = TestModeManager(enabled=test_mode, root_path=root_path)
        self.git_manager = GitManager(self.test_mode)
        self.pip_installer = PipInstaller(self.test_mode)
        self.git_only = git_only
        self.max_depth = max_depth

    def set_ignored_subprojects(self, subproject_names: List[str]) -> None:
        """Set which subprojects to ignore."""
        self.ignored_subprojects = set(subproject_names)

    def run(self) -> None:
        """Run the subproject manager: discover subprojects, process each, then print summary."""
        self.process_subprojects()
        print(self.test_mode.get_summary())

    def process_subprojects(self) -> None:
        """Discover and process all subprojects."""
        subprojects = SubprojectFinder.find_subprojects(self.root_path, self.max_depth)
        self.test_mode.subprojects = subprojects

        for subproject in subprojects:
            if subproject.name in self.ignored_subprojects:
                logger.info("Skipping ignored subproject: %s", subproject.name)
                continue
            try:
                self.process_subproject(subproject)
            except Exception as e:
                logger.error("Error processing subproject %s: %s", subproject.name, e)
                raise

    def process_subproject(self, subproject: SubprojectInfo) -> None:
        """Process a single subproject: Git then pip (unless --git-only)."""
        if subproject.path is None:
            return
        logger.info("Processing subproject: %s", subproject.name)

        try:
            if self.git_manager.is_git_repo(subproject.path):
                github_url = self.git_manager.get_remote_url(subproject.path)
                if github_url:
                    subproject.github_url = github_url
                    logger.info("GitHub URL: %s", github_url)

                is_clean, status_msg, was_cleaned_by_filtering = self.git_manager.get_git_status(
                    subproject.path
                )
                logger.info("Git status: %s", status_msg)
                self.test_mode.log_operation(
                    True,
                    f"Git status: {status_msg}",
                    project_name=subproject.name,
                )

                success, message = self.git_manager.update_repository(subproject.path)
                if not success:
                    logger.warning("Warning: Git update failed for %s", subproject.name)
                    self.test_mode.log_operation(
                        False,
                        f"Git update failed: {message}",
                        project_name=subproject.name,
                    )
                    subproject.error = f"Git update failed: {message}"
                    return
                if "up to date" not in message.lower():
                    logger.info("%s", message)
                    self.test_mode.log_operation(True, message, project_name=subproject.name)
                else:
                    self.test_mode.log_operation(
                        True, "Repository up to date", project_name=subproject.name
                    )

                last_commit = GitHubCommitChecker.get_last_commit_date(subproject.path)
                if last_commit:
                    logger.info("Last commit date: %s", last_commit)
                    subproject.last_commit_date = last_commit
                else:
                    logger.info("Could not determine last commit date for %s", subproject.name)

            if self.git_only:
                logger.info("Skipping pip installations (--git-only mode)")
                return

            failed_packages: List[str] = []

            for package_name, package in subproject.requirements.items():
                version_str = str(package.version) if package.version else None
                success, error = self.pip_installer.install_package(
                    package_name, version_str, self.env_path
                )
                if success:
                    logger.info("Installed %s", package)
                    self.test_mode.log_operation(
                        True, f"Installed {package}", project_name=subproject.name
                    )
                else:
                    logger.warning("Failed to install %s: %s", package, error)
                    self.test_mode.log_operation(
                        False,
                        f"Failed to install {package}: {error}",
                        project_name=subproject.name,
                    )
                    failed_packages.append(str(package))

            if failed_packages:
                error_msg = "Failed to install packages: " + ", ".join(failed_packages)
                logger.warning("%s", error_msg)
                subproject.error = error_msg

        except Exception as e:
            error_msg = f"Error processing subproject: {e!s}"
            logger.error("%s", error_msg)
            subproject.error = error_msg
            self.test_mode.log_operation(
                False, error_msg, project_name=subproject.name
            )
