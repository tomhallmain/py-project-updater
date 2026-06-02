"""SubprojectManager: main orchestrator for subproject Git and pip operations."""

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from py_project_updater.models import Package, SubprojectInfo
from py_project_updater.reporting import RunReporter
from py_project_updater.config import (
    DEFAULT_MAIN_WEIGHT, DEFAULT_OUTLIER_THRESHOLD,
    DEFAULT_RECOVERY_DIR,
    DEFAULT_STASH_FILE_THRESHOLD, DEFAULT_STASH_LINE_THRESHOLD,
)
from py_project_updater.services.conflict_resolver import ConflictResolver
from py_project_updater.services.finder import SubprojectFinder
from py_project_updater.services.git_commit import GitCommitChecker
from py_project_updater.services.git import GitManager
from py_project_updater.services.pip_installer import PipInstaller
from py_project_updater.services.version_comparator import VersionComparator

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
        version_tolerance: str = "minor",
        main_weight: float = DEFAULT_MAIN_WEIGHT,
        outlier_threshold: float = DEFAULT_OUTLIER_THRESHOLD,
        stash_file_threshold: float = DEFAULT_STASH_FILE_THRESHOLD,
        stash_line_threshold: int = DEFAULT_STASH_LINE_THRESHOLD,
        recovery_dir: Path = DEFAULT_RECOVERY_DIR,
    ):
        self.root_path = root_path
        self.env_path = env_path
        self.ignored_subprojects: set = set()
        self.main_requirements: Dict[str, Package] = {}
        self.outlier_map: Dict[str, List[str]] = {}
        self.version_tolerance = version_tolerance
        self.main_weight = main_weight
        self.outlier_threshold = outlier_threshold
        self.stash_file_threshold = stash_file_threshold
        self.stash_line_threshold = stash_line_threshold
        self.recovery_dir = recovery_dir
        self.reporter = RunReporter(enabled=test_mode, root_path=root_path)
        self.git_manager = GitManager(self.reporter)
        self.pip_installer = PipInstaller(self.reporter)
        self.git_only = git_only
        self.max_depth = max_depth

    def set_ignored_subprojects(self, subproject_names: List[str]) -> None:
        """Set which subprojects to ignore."""
        self.ignored_subprojects = set(subproject_names)

    def _save_stash_backup(
        self,
        subproject: SubprojectInfo,
        diff: str,
    ) -> Optional[Path]:
        """Write a stash diff to the recovery directory.

        Creates <recovery_dir>/<subproject_name>/stash_<timestamp>.patch and
        a companion stash_info.txt. Returns the patch path on success, or None
        if writing failed (error is logged; the caller should not raise).
        """
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            sub_dir = self.recovery_dir / subproject.name
            sub_dir.mkdir(parents=True, exist_ok=True)

            patch_path = sub_dir / f"stash_{timestamp}.patch"
            patch_path.write_text(diff, encoding="utf-8")

            info_lines = [
                f"Subproject : {subproject.name}",
                f"Path       : {subproject.path}",
                f"GitHub URL : {subproject.github_url or 'unknown'}",
                f"Timestamp  : {timestamp}",
                "",
                "To re-apply: git apply <patch_file>",
            ]
            (sub_dir / "stash_info.txt").write_text(
                "\n".join(info_lines), encoding="utf-8"
            )

            logger.info("Stash backup written to %s", patch_path)
            return patch_path

        except PermissionError as e:
            logger.error(
                "Cannot write stash backup for %s — directory not writable: %s. "
                "The stash has been dropped; re-apply the patch manually.",
                subproject.name, e,
            )
            return None
        except Exception as e:
            logger.error(
                "Failed to write stash backup for %s: %s", subproject.name, e
            )
            return None

    def run(self) -> None:
        """Run the subproject manager: discover subprojects, process each, then print summary."""
        self.process_subprojects()
        print(self.reporter.get_summary())

    def process_subprojects(self) -> None:
        """Discover and process all subprojects."""
        subprojects = SubprojectFinder.find_subprojects(self.root_path, self.max_depth)
        self.reporter.subprojects = subprojects

        main = next((s for s in subprojects if s.path == self.root_path), None)
        self.main_requirements = main.requirements if main else {}
        if self.main_requirements:
            logger.info(
                "Loaded %d main project requirements for conflict checking",
                len(self.main_requirements),
            )

        # Abort before touching any subproject if the main project's uncommitted
        # changes are too large to stash safely. Skipped in test mode.
        if main is not None and main.path is not None and not self.reporter.enabled:
            is_clean, status_msg, _ = self.git_manager.get_git_status(main.path)
            if not is_clean and "uncommitted changes" in status_msg.lower():
                volume_ok, volume_reason = self.git_manager.check_change_volume(
                    main.path,
                    file_threshold=self.stash_file_threshold,
                    line_threshold=self.stash_line_threshold,
                )
                if not volume_ok:
                    raise RuntimeError(
                        f"Main project '{main.name}' has uncommitted changes that exceed "
                        f"safe stashing limits ({volume_reason}). Resolve or stash manually "
                        f"before running in execute mode."
                    )
                logger.info(
                    "Main project has uncommitted changes within stashing limits "
                    "— will stash, pull, and restore."
                )

        active_subs = [
            s for s in subprojects
            if s.path != self.root_path and s.name not in self.ignored_subprojects and s.path
        ]

        main_commit_date = GitCommitChecker.get_last_commit_date(self.root_path)
        sub_commit_dates = {
            s.name: GitCommitChecker.get_last_commit_date(s.path)
            for s in active_subs
        }
        sub_recency_factors = ConflictResolver.compute_recency_factors(
            main_commit_date=main_commit_date,
            sub_commit_dates=sub_commit_dates,
        )

        sub_requirements = {s.name: s.requirements for s in active_subs}
        self.outlier_map = ConflictResolver.find_outliers(
            main_requirements=self.main_requirements,
            sub_requirements=sub_requirements,
            main_weight=self.main_weight,
            std_threshold=self.outlier_threshold,
            sub_recency_factors=sub_recency_factors,
        )
        for pkg, outlier_subs in self.outlier_map.items():
            logger.info(
                "Outlier subprojects for %s: %s", pkg, ", ".join(outlier_subs)
            )

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

                git_status = self.git_manager.get_git_status(subproject.path)
                _, status_msg, _ = git_status
                logger.info("Git status: %s", status_msg)
                self.reporter.log_operation(
                    True,
                    f"Git status: {status_msg}",
                    project_name=subproject.name,
                )

                success, message, stash_diff = self.git_manager.update_repository(
                    subproject.path,
                    status=git_status,
                    file_threshold=self.stash_file_threshold,
                    line_threshold=self.stash_line_threshold,
                )
                if stash_diff:
                    backup_path = self._save_stash_backup(subproject, stash_diff)
                    if backup_path:
                        logger.warning(
                            "Stash pop failed for %s — local changes saved to %s. "
                            "Re-apply with: git apply %s",
                            subproject.name, backup_path, backup_path,
                        )
                if not success:
                    logger.warning("Warning: Git update failed for %s", subproject.name)
                    self.reporter.log_operation(
                        False,
                        f"Git update failed: {message}",
                        project_name=subproject.name,
                    )
                    subproject.error = f"Git update failed: {message}"
                    return
                if "up to date" not in message.lower():
                    logger.info("%s", message)
                    self.reporter.log_operation(True, message, project_name=subproject.name)
                else:
                    self.reporter.log_operation(
                        True, "Repository up to date", project_name=subproject.name
                    )

                last_commit = GitCommitChecker.get_last_commit_date(subproject.path)
                if last_commit:
                    logger.info("Last commit date: %s", last_commit)
                    subproject.last_commit_date = last_commit
                else:
                    logger.info("Could not determine last commit date for %s", subproject.name)

            if self.git_only:
                logger.info("Skipping pip installations (--git-only mode)")
                return

            if self.main_requirements and subproject.path != self.root_path:
                for package_name, package in subproject.requirements.items():
                    main_pkg = self.main_requirements.get(package_name)
                    if main_pkg and VersionComparator.compare_versions(main_pkg, package, self.version_tolerance):
                        conflict_msg = (
                            f"Version conflict for {package_name}: "
                            f"main requires {main_pkg.version}, "
                            f"subproject requires {package.version}"
                        )
                        logger.warning(conflict_msg)
                        self.reporter.log_operation(
                            True,
                            f"Warning: {conflict_msg}",
                            project_name=subproject.name,
                        )

            failed_packages: List[str] = []

            for package_name, package in subproject.requirements.items():
                if subproject.name in self.outlier_map.get(package_name, []):
                    msg = (
                        f"Skipped outlier: {package_name} in {subproject.name} "
                        f"requires {package.version}, which is below the version consensus"
                    )
                    logger.warning(msg)
                    self.reporter.log_operation(
                        True, f"Warning: {msg}", project_name=subproject.name
                    )
                    continue

                version_str = str(package.version) if package.version else None
                success, error = self.pip_installer.install_package(
                    package_name, version_str, self.env_path
                )
                if success:
                    logger.info("Installed %s", package)
                    self.reporter.log_operation(
                        True, f"Installed {package}", project_name=subproject.name
                    )
                else:
                    logger.warning("Failed to install %s: %s", package, error)
                    self.reporter.log_operation(
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
            self.reporter.log_operation(
                False, error_msg, project_name=subproject.name
            )
