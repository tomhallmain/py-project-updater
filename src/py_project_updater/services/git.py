"""Git operations for subprojects."""

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from py_project_updater.reporting import TestModeManager

logger = logging.getLogger(__name__)


class GitManager:
    """Handles Git operations for subprojects."""

    PYTHON_IGNORE_PATTERNS = [
        "*.pyc",
        "*.pyo",
        "*.pyd",
        "__pycache__/",
        "*.so",
        "*.egg-info/",
        ".pytest_cache/",
        ".mypy_cache/",
        ".coverage",
        "htmlcov/",
        ".tox/",
        ".eggs/",
        "build/",
        "dist/",
        "*.egg",
    ]

    def __init__(self, test_mode: TestModeManager):
        self.test_mode = test_mode

    def is_git_repo(self, path: Path) -> bool:
        """Check if a directory is a Git repository."""
        if self.test_mode.enabled:
            self.test_mode.log_operation(
                True,
                f"Checking if {path} is a Git repository",
                "git rev-parse --is-inside-work-tree",
            )
            return True

        try:
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=path,
                capture_output=True,
                text=True,
            )
            return result.returncode == 0 and result.stdout.strip() == "true"
        except Exception:
            return False

    def get_remote_url(self, path: Path) -> Optional[str]:
        """Get the remote URL for a Git repository."""
        if self.test_mode.enabled:
            self.test_mode.log_operation(
                True,
                f"Getting remote URL for {path}",
                "git remote get-url origin",
            )
            return f"https://github.com/test/{path.name}.git"

        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=path,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                url = result.stdout.strip()
                if url.startswith("git@github.com:"):
                    url = url.replace("git@github.com:", "https://github.com/")
                return url
            return None
        except Exception:
            return None

    def _clean_python_artifacts(self, path: Path) -> None:
        """Restore modified/deleted files to their tracked state."""
        if self.test_mode.enabled:
            self.test_mode.log_operation(
                True,
                f"Would restore modified/deleted files in {path}",
                "git checkout -- .",
            )
            return

        try:
            subprocess.run(
                ["git", "checkout", "--", "."],
                cwd=path,
                capture_output=True,
                text=True,
            )

            tracked_result = subprocess.run(
                ["git", "ls-files"],
                cwd=path,
                capture_output=True,
                text=True,
            )

            if tracked_result.returncode != 0:
                logger.warning(f"Failed to get tracked files: {tracked_result.stderr}")
                return

            tracked_files = set()
            for file in tracked_result.stdout.strip().split("\n"):
                if file:
                    tracked_files.add(file)
                    tracked_files.add(file.replace("/", "\\"))

            for pattern in self.PYTHON_IGNORE_PATTERNS:
                if pattern.endswith("/"):
                    dir_pattern = pattern.rstrip("/")
                    for dir_path in path.rglob(dir_pattern):
                        if dir_path.is_dir():
                            has_tracked_files = False
                            for file_path in dir_path.rglob("*"):
                                if file_path.is_file():
                                    rel_path = str(file_path.relative_to(path))
                                    if (
                                        rel_path in tracked_files
                                        or rel_path.replace("\\", "/") in tracked_files
                                    ):
                                        has_tracked_files = True
                                        break

                            if not has_tracked_files:
                                try:
                                    shutil.rmtree(dir_path)
                                    logger.info(f"Removed directory: {dir_path}")
                                except Exception as e:
                                    logger.warning(
                                        f"Failed to remove directory {dir_path}: {str(e)}"
                                    )
                else:
                    for file_path in path.rglob(pattern):
                        if file_path.is_file():
                            rel_path = str(file_path.relative_to(path))
                            if (
                                rel_path not in tracked_files
                                and rel_path.replace("\\", "/") not in tracked_files
                            ):
                                try:
                                    file_path.unlink()
                                    logger.info(f"Removed file: {file_path}")
                                except Exception as e:
                                    logger.warning(
                                        f"Failed to remove file {file_path}: {str(e)}"
                                    )
        except Exception as e:
            logger.warning(f"Warning: Failed to restore files: {str(e)}")

    def _is_ignored_change(self, status_line: str) -> bool:
        """Check if a Git status line should be ignored."""
        if len(status_line) < 3:
            logger.debug(f"Status line too short: {status_line}")
            return False

        index_status = status_line[0]
        working_status = status_line[1]
        filename = status_line[3:].strip()

        logger.debug(f"Checking status line: {status_line}")
        logger.debug(
            f"Index status: {index_status}, Working status: {working_status}, "
            f"Filename: {filename}"
        )

        if working_status in ["?", "M"] or index_status in ["M", "A"]:
            for pattern in self.PYTHON_IGNORE_PATTERNS:
                matches = (
                    filename.endswith(pattern.rstrip("/"))
                    or (
                        pattern.endswith("/")
                        and filename.startswith(pattern)
                    )
                )
                if matches:
                    logger.debug(f"Match found! Pattern: {pattern}, Filename: {filename}")
                    return True
            logger.debug(f"No matches found for filename: {filename}")
            return False

        logger.debug(f"Status not relevant for ignore check: {status_line}")
        return False

    def get_git_status(self, path: Path) -> Tuple[bool, str, bool]:
        """Check Git status and return (is_clean, status_message, was_cleaned_by_filtering)."""
        try:
            status_result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=path,
                capture_output=True,
                text=True,
            )

            if status_result.returncode != 0:
                return False, "Failed to get Git status", False

            raw_status_lines = status_result.stdout.strip().split("\n")
            logger.debug(f"Raw Git status lines: {raw_status_lines}")

            relevant_changes = []
            for line in raw_status_lines:
                if line:
                    logger.debug(f"Processing status line: {line}")
                    if not self._is_ignored_change(line):
                        relevant_changes.append(line)
                        logger.debug(f"Added to relevant changes: {line}")

            was_cleaned_by_filtering = len(raw_status_lines) > len(relevant_changes)

            if relevant_changes:
                logger.debug(f"Found relevant changes: {relevant_changes}")
                return False, "Repository has uncommitted changes", was_cleaned_by_filtering

            unpushed_result = subprocess.run(
                ["git", "cherry", "-v"],
                cwd=path,
                capture_output=True,
                text=True,
            )

            if unpushed_result.stdout.strip():
                return False, "Repository has unpushed commits", was_cleaned_by_filtering

            return True, "Repository is clean", was_cleaned_by_filtering
        except Exception as e:
            return False, f"Error checking Git status: {str(e)}", False

    def update_repository(self, path: Path) -> Tuple[bool, str]:
        """Update the repository based on its status."""
        is_clean, status_msg, was_cleaned_by_filtering = self.get_git_status(path)

        if self.test_mode.enabled:
            if not is_clean or "up to date" not in status_msg.lower():
                operation = "pull" if is_clean else "fetch"
                self.test_mode.log_operation(
                    True,
                    f"Would {operation} changes for {path}",
                    f"git {operation}",
                    [f"Update repository at {path}"],
                )
                return True, f"Would {operation} changes"
            return True, "Repository up to date"

        try:
            if is_clean:
                if was_cleaned_by_filtering:
                    self._clean_python_artifacts(path)

                is_clean_after, status_after, _ = self.get_git_status(path)
                if not is_clean_after:
                    logger.warning(
                        f"Repository still not clean after cleaning artifacts: "
                        f"{status_after}"
                    )
                    return False, f"Repository not clean: {status_after}"

                pull_result = subprocess.run(
                    ["git", "pull"],
                    cwd=path,
                    capture_output=True,
                    text=True,
                )
                if pull_result.returncode == 0:
                    changes = pull_result.stdout.strip()
                    if changes:
                        return True, f"Pulled changes: {changes}"
                    return True, "Repository up to date"
                return False, f"Failed to pull changes: {pull_result.stderr.strip()}"
            else:
                fetch_result = subprocess.run(
                    ["git", "fetch"],
                    cwd=path,
                    capture_output=True,
                    text=True,
                )
                if fetch_result.returncode == 0:
                    return True, "Fetched changes (repository not clean)"
                return False, f"Failed to fetch changes: {fetch_result.stderr.strip()}"
        except Exception as e:
            return False, f"Error updating repository: {str(e)}"
