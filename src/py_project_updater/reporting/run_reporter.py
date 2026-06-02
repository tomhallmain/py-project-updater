"""Test mode operations and summary formatting."""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from py_project_updater.models import OperationResult, SubprojectInfo

logger = logging.getLogger(__name__)


class RunReporter:
    """Records operations and formats the run summary."""

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

    def get_summary(self) -> str:
        """Get a concise summary of all operations performed."""
        logger.debug(f"Total operations: {len(self.operations)}")

        project_ops: Dict[str, List[OperationResult]] = {}
        for op in self.operations:
            if op.project_name:
                project_ops.setdefault(op.project_name, []).append(op)

        summary = ["\nTest Mode Summary:" if self.enabled else "\nRun Summary:"]
        success_projects: List[Tuple] = []
        warning_projects: List[Tuple[str, str]] = []
        error_projects: List[Tuple[str, str]] = []
        error_details: List[Tuple[str, str]] = []

        project_info = {p.name: p for p in self.subprojects}

        for project, ops in project_ops.items():
            if project_info.get(project) and project_info[project].path == self.root_path:
                continue

            has_errors = any(not op.success for op in ops)
            has_warnings = any("warning" in op.message.lower() for op in ops)

            git_status = None
            git_operation = None
            for op in ops:
                if op.success and (
                    "pull" in op.message.lower() or "fetch" in op.message.lower()
                ):
                    action = "pull" if "pull" in op.message.lower() else "fetch"
                    git_operation = f"would {action}" if op.message.lower().startswith("would") else action
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
                    (project, git_status, git_operation, subproject_error)
                )

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
            max_name_len = max(len(name) for name, _, _, _ in success_projects) + 1
            max_git_len = (
                max(len(git_status or "") for _, git_status, _, _ in success_projects) + 1
            )
            max_error_len = max(len(error or "") for _, _, _, error in success_projects) + 1

            summary.append(
                f"  {'Project':<{max_name_len}}  "
                f"{'Git Status':<{max_git_len}}  {'Operation':<10}  {'Error':<{max_error_len}}"
            )

            for name, git_status, git_operation, error in sorted(
                success_projects, key=sort_key
            ):
                operation = f"({git_operation})" if git_operation else ""
                error_fmt = (
                    error.replace("\n", "\n" + " " * (max_name_len + 4)) if error else ""
                )
                summary.append(
                    f"  {name:<{max_name_len}}  "
                    f"{git_status or '':<{max_git_len}}  {operation:<10}  "
                    f"{error_fmt or '':<{max_error_len}}"
                )

        # Global pip phase results — no project_name, message contains "install"
        pip_ops = [
            op for op in self.operations
            if op.project_name is None and "install" in op.message.lower()
        ]
        if pip_ops:
            if self.enabled:
                pip_count = sum(1 for op in pip_ops if op.success)
                summary.append(f"\nWould install: {pip_count} package{'s' if pip_count != 1 else ''}")
            else:
                pip_success = [op for op in pip_ops if op.success]
                pip_failed = [op for op in pip_ops if not op.success]
                line = f"\nPackages installed: {len(pip_success)}"
                if pip_failed:
                    line += f"  ({len(pip_failed)} failed)"
                summary.append(line)
                if pip_failed:
                    summary.append("  Failed:")
                    for op in pip_failed:
                        summary.append(f"    {op.message}")

        if error_details:
            summary.append("\nDetailed Error Information:")
            max_name_len = max(len(name) for name, _ in error_details)
            for project, error in sorted(error_details, key=sort_key):
                formatted_error = error.replace(
                    "\n", "\n" + " " * (max_name_len + 4)
                )
                summary.append(f"  {project:<{max_name_len}}  {formatted_error}")

        return "\n".join(summary)
