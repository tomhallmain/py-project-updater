"""Test mode operations and summary formatting."""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from py_project_updater.models import OperationResult, SubprojectInfo

logger = logging.getLogger(__name__)


class TestModeManager:
    """Manages test mode operations and logging."""

    def __init__(
        self,
        enabled: bool = False,
        subprojects: Optional[List[SubprojectInfo]] = None,
        root_path: Optional[Path] = None,
    ):
        self.enabled = enabled
        self.operations: List[OperationResult] = []
        self.subprojects = subprojects or []
        self.root_path = root_path

    def log_operation(
        self,
        success: bool,
        message: str,
        command: Optional[str] = None,
        changes: Optional[List[str]] = None,
        project_name: Optional[str] = None,
    ) -> None:
        """Log an operation and its result."""
        result = OperationResult(
            success=success,
            message=message,
            command=command,
            changes=changes or [],
            project_name=project_name,
        )
        self.operations.append(result)

        if self.enabled:
            logger.info(f"[TEST] {message}")
            if command:
                logger.info(f"[TEST] Would execute: {command}")
            if changes:
                for change in changes:
                    logger.info(f"[TEST] Would make change: {change}")
        else:
            if success:
                logger.info(message)
            else:
                logger.warning(message)

    def _analyze_package_conflicts(
        self,
    ) -> Tuple[Dict[str, List[Tuple[str, str]]], Dict[str, List[str]]]:
        """Analyze package installations for conflicts and unique installs."""
        package_versions: Dict[str, Dict[str, str]] = {}
        unique_packages: Dict[str, List[str]] = {}

        for op in self.operations:
            if not op.success or not op.project_name:
                continue

            if "installed" in op.message.lower():
                parts = op.message.split()
                if len(parts) >= 2:
                    package_spec = parts[1]
                    if "==" in package_spec:
                        package, version = package_spec.split("==", 1)
                    else:
                        package = package_spec
                        version = "any"

                    if package not in package_versions:
                        package_versions[package] = {}
                    package_versions[package][op.project_name] = version

        conflicts: Dict[str, List[Tuple[str, str]]] = {}
        for package, versions in package_versions.items():
            if len(versions) > 1:
                unique_versions = set(versions.values())
                if len(unique_versions) > 1:
                    conflicts[package] = [(proj, ver) for proj, ver in versions.items()]
            else:
                project = next(iter(versions.keys()))
                if project not in unique_packages:
                    unique_packages[project] = []
                unique_packages[project].append(package)

        return conflicts, unique_packages

    def get_summary(self) -> str:
        """Get a concise summary of all operations that would be performed."""
        logger.debug(f"Total operations: {len(self.operations)}")
        logger.debug(f"Operations: {self.operations}")

        project_ops: Dict[str, List[OperationResult]] = {}
        for op in self.operations:
            if op.project_name:
                if op.project_name not in project_ops:
                    project_ops[op.project_name] = []
                project_ops[op.project_name].append(op)

        logger.debug(f"Projects with operations: {list(project_ops.keys())}")

        summary = ["\nTest Mode Summary:"]
        success_projects: List[Tuple] = []
        warning_projects: List[Tuple[str, str]] = []
        error_projects: List[Tuple[str, str]] = []
        error_details: List[Tuple[str, str]] = []

        project_info = {p.name: p for p in self.subprojects}
        logger.debug(f"Project info: {project_info}")

        for project, ops in project_ops.items():
            logger.debug(f"Processing project: {project}")
            if project_info.get(project) and project_info[project].path == self.root_path:
                logger.debug(f"Skipping main project: {project}")
                continue

            has_errors = any(not op.success for op in ops)
            has_warnings = any("warning" in op.message.lower() for op in ops)
            install_count = sum(
                1 for op in ops if op.success and "installed" in op.message.lower()
            )

            git_status = None
            git_operation = None
            for op in ops:
                if op.success and (
                    "pull" in op.message.lower() or "fetch" in op.message.lower()
                ):
                    git_operation = "pull" if "pull" in op.message.lower() else "fetch"
                elif op.success and "status" in op.message.lower():
                    git_status = op.message.split(":")[-1].strip()

            subproject_error = project_info.get(
                project, SubprojectInfo(None, None, project)
            ).error

            if has_errors:
                error_msg = next(op for op in ops if not op.success).message
                error_projects.append((project, error_msg))
                if subproject_error:
                    error_details.append((project, subproject_error))
            elif has_warnings:
                warning_projects.append(
                    (project, next(op for op in ops if "warning" in op.message.lower()).message)
                )
            else:
                success_projects.append(
                    (project, install_count, git_status, git_operation, subproject_error)
                )

        logger.debug(f"Success projects: {success_projects}")
        logger.debug(f"Warning projects: {warning_projects}")
        logger.debug(f"Error projects: {error_projects}")

        def sort_key(item):
            project_name = item[0]
            info = project_info.get(project_name)
            if not info:
                return (0, 4, "", project_name)

            git_status = None
            for op in project_ops.get(project_name, []):
                if op.success and "status" in op.message.lower():
                    git_status = op.message.split(":")[-1].strip()
                    break

            parent_name = info.parent_path.name if info.parent_path else ""
            status_order = {
                "Repository is clean": 0,
                "Repository has uncommitted changes": 1,
                "Repository has unpushed commits": 2,
            }
            git_status_order = status_order.get(git_status, 3) if git_status else 3
            return (parent_name, git_status_order, git_status or "", project_name)

        if error_projects:
            summary.append("\nProjects with errors:")
            max_name_len = max(len(name) for name, _ in error_projects)
            summary.extend(
                f"  {name:<{max_name_len}}  {msg}"
                for name, msg in sorted(error_projects, key=sort_key)
            )

        if warning_projects:
            summary.append("\nProjects with warnings:")
            max_name_len = max(len(name) for name, _ in warning_projects)
            summary.extend(
                f"  {name:<{max_name_len}}  {msg}"
                for name, msg in sorted(warning_projects, key=sort_key)
            )

        if success_projects:
            summary.append("\nSuccessful projects:")
            max_name_len = max(len(name) for name, _, _, _, _ in success_projects) + 1
            max_pkg_len = (
                max(len(str(install_count)) for _, install_count, _, _, _ in success_projects)
                + 1
            )
            max_git_len = (
                max(len(git_status or "") for _, _, git_status, _, _ in success_projects) + 1
            )
            max_error_len = max(len(error or "") for _, _, _, _, error in success_projects) + 1

            summary.append(
                f"  {'Project':<{max_name_len}}  {'Pkgs':<{max_pkg_len}}  "
                f"{'Git Status':<{max_git_len}}  {'Operation':<10}  {'Error':<{max_error_len}}"
            )

            for name, install_count, git_status, git_operation, error in sorted(
                success_projects, key=sort_key
            ):
                install_str = str(install_count) if install_count else ""
                operation = f"({git_operation})" if git_operation else ""
                error_fmt = (
                    error.replace("\n", "\n" + " " * (max_name_len + 4)) if error else ""
                )
                summary.append(
                    f"  {name:<{max_name_len}}  {install_str:<{max_pkg_len}}  "
                    f"{git_status or '':<{max_git_len}}  {operation:<10}  "
                    f"{error_fmt or '':<{max_error_len}}"
                )

        conflicts, unique_packages = self._analyze_package_conflicts()

        if conflicts:
            summary.append("\nPackage version conflicts:")
            max_pkg_len = max(len(pkg) for pkg in conflicts.keys())
            for package, versions in conflicts.items():
                summary.append(
                    f"  {package:<{max_pkg_len}}  "
                    f"{', '.join(f'{proj}:{ver}' for proj, ver in versions)}"
                )

        if unique_packages:
            summary.append("\nUnique package installations:")
            max_proj_len = max(len(proj) for proj in unique_packages.keys())
            for project, packages in unique_packages.items():
                if packages:
                    summary.append(
                        f"  {project:<{max_proj_len}}  {', '.join(sorted(packages))}"
                    )

        if error_details:
            summary.append("\nDetailed Error Information:")
            max_name_len = max(len(name) for name, _ in error_details)
            for project, error in sorted(error_details, key=sort_key):
                formatted_error = error.replace(
                    "\n", "\n" + " " * (max_name_len + 4)
                )
                summary.append(f"  {project:<{max_name_len}}  {formatted_error}")

        return "\n".join(summary)
