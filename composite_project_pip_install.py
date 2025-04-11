"""
Composite Project Pip Installer

This script helps manage pip installations across multiple Python subprojects in a composite project. It can:
- Find and process requirements.txt files in subprojects
- Update Git repositories
- Install packages in the correct virtual environment
- Show what changes would be made (test mode)

Usage:
    python composite_project_pip_install.py --env-path PATH [options]

Required Arguments:
    --root-path PATH   Root directory containing subprojects
    --env-path PATH    Path to your Python virtual environment

Optional Arguments:
    --execute          Actually make changes (default: test mode - no changes)
    --git-only         Only perform Git operations, skip pip installations
    --max-depth N      Maximum depth to search for requirements files (default: 2)
    --ignore NAME      List of subproject names to ignore (can specify multiple)
    --log-level LEVEL  Set logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    --log-file PATH    Path to log file (default: composite_project_pip_install_{main_project_name}.log)

Examples:
    # Test mode (no changes)
    python composite_project_pip_install.py --root-path C:/path/to/root --env-path C:/path/to/env

    # Execute changes
    python composite_project_pip_install.py --root-path C:/path/to/root --env-path C:/path/to/env --execute

    # Git operations only
    python composite_project_pip_install.py --root-path C:/path/to/root --env-path C:/path/to/env --git-only

    # Custom root path and ignored subprojects
    python composite_project_pip_install.py --root-path C:/path/to/root --env-path C:/path/to/env --ignore tests venv
"""

import argparse
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from enum import Enum
import logging
import os
from packaging import version
from pathlib import Path
import re
import requests
import subprocess
from typing import List, Optional, Dict, Union, Tuple

# Create logger but don't configure it yet
logger = logging.getLogger(__name__)

class VersionSpecifier(Enum):
    """Enum for different version specifiers."""
    EXACT = '=='
    GREATER_EQUAL = '>='
    LESS_EQUAL = '<='
    GREATER = '>'
    LESS = '<'
    COMPATIBLE = '~='
    NOT_EQUAL = '!='

@dataclass
class Version:
    """Represents a package version with its specifier."""
    specifier: VersionSpecifier
    version: str
    
    def __str__(self) -> str:
        return f"{self.specifier.value}{self.version}"
    
    def is_compatible_with(self, other_version: str) -> bool:
        """Check if this version specifier is compatible with another version."""
        try:
            current = version.parse(self.version)
            other = version.parse(other_version)
            
            if self.specifier == VersionSpecifier.EXACT:
                return current == other
            elif self.specifier == VersionSpecifier.GREATER_EQUAL:
                return other >= current
            elif self.specifier == VersionSpecifier.LESS_EQUAL:
                return other <= current
            elif self.specifier == VersionSpecifier.GREATER:
                return other > current
            elif self.specifier == VersionSpecifier.LESS:
                return other < current
            elif self.specifier == VersionSpecifier.COMPATIBLE:
                # ~= means compatible release, which means >= current and < next major version
                next_major = version.Version(f"{current.major + 1}.0.0")
                return other >= current and other < next_major
            elif self.specifier == VersionSpecifier.NOT_EQUAL:
                return other != current
        except version.InvalidVersion:
            return False
        return False

@dataclass
class Package:
    """Represents a Python package with its version requirements."""
    name: str
    version: Optional[Version] = None
    
    @classmethod
    def from_string(cls, package_str: str) -> 'Package':
        """Create a Package instance from a requirements.txt line."""
        # Handle cases with no version specifier
        if '==' not in package_str and '>=' not in package_str and '<=' not in package_str and \
           '>' not in package_str and '<' not in package_str and '~=' not in package_str and '!=' not in package_str:
            return cls(name=package_str.strip())
        
        # Find the first version specifier
        specifiers = [s for s in VersionSpecifier if s.value in package_str]
        if not specifiers:
            return cls(name=package_str.strip())
            
        specifier = specifiers[0]
        name, ver = package_str.split(specifier.value, 1)
        return cls(name=name.strip(), version=Version(specifier=specifier, version=ver.strip()))
    
    def __str__(self) -> str:
        if self.version:
            return f"{self.name}{self.version}"
        return self.name

@dataclass
class SubprojectInfo:
    """Represents information about a subproject."""
    path: Path
    requirements_file: Path
    name: str
    github_url: Optional[str] = None
    last_commit_date: Optional[datetime] = None
    requirements: Dict[str, Package] = None
    depth: int = 0  # Depth from root
    parent_path: Optional[Path] = None  # Path to parent project if nested
    is_nested: bool = False  # Whether this is a nested requirements file
    error: Optional[str] = None  # Track any errors that occurred during processing

class SubprojectFinder:
    """Finds all subprojects with requirements.txt files."""
    
    @staticmethod
    def _create_subproject(path: Path, root_path: Path, max_depth: int, requirements_file: Optional[Path] = None) -> Optional[SubprojectInfo]:
        """Create a SubprojectInfo object for a given path.
        
        Args:
            path: Path to the subproject directory
            root_path: Root directory of the project
            max_depth: Maximum depth to search for requirements files
            requirements_file: Optional path to requirements.txt file
            
        Returns:
            SubprojectInfo object if valid, None if path should be skipped
        """
        # Skip if in a virtual environment directory
        if any(part.startswith('.') for part in path.parts):
            return None
            
        # Calculate depth from root
        depth = len(path.relative_to(root_path).parts)
        
        # Skip if too deep
        if depth > max_depth:
            return None
            
        # Find the parent project (closest ancestor with requirements.txt or .git)
        parent_path = None
        is_nested = False
        for parent in path.parents:
            if parent == root_path:
                break
            if (parent / 'requirements.txt').exists() or (parent / '.git').is_dir():
                parent_path = parent
                is_nested = True
                break
        
        # Create new subproject
        subproject_name = path.name
        subproject = SubprojectInfo(
            path=path,
            requirements_file=requirements_file,
            name=subproject_name,
            requirements=SubprojectFinder._parse_requirements(requirements_file) if requirements_file else {},
            depth=depth,
            parent_path=parent_path,
            is_nested=is_nested
        )
        
        return subproject

    @staticmethod
    def find_subprojects(root_path: Path, max_depth: int = 2) -> List[SubprojectInfo]:
        """Find all subprojects with requirements.txt files or Git repositories.
        
        Args:
            root_path: Root directory to search from
            max_depth: Maximum depth to search for requirements files (default: 2)
        """
        subprojects = []
        processed_paths = set()  # Track paths we've already processed
        
        # First, find all Git repositories
        for git_dir in root_path.rglob('.git'):
            if git_dir.is_dir():
                subproject_path = git_dir.parent
                if subproject_path not in processed_paths:
                    processed_paths.add(subproject_path)
                    
                    # Look for requirements.txt in this directory
                    req_file = subproject_path / 'requirements.txt'
                    subproject = SubprojectFinder._create_subproject(
                        subproject_path,
                        root_path,
                        max_depth,
                        req_file if req_file.exists() else None
                    )
                    
                    if subproject:
                        subprojects.append(subproject)
        
        # Then, find all requirements.txt files that weren't already processed
        for req_file in root_path.rglob('requirements.txt'):
            subproject_path = req_file.parent
            if subproject_path not in processed_paths:
                processed_paths.add(subproject_path)
                
                subproject = SubprojectFinder._create_subproject(
                    subproject_path,
                    root_path,
                    max_depth,
                    req_file
                )
                
                if subproject:
                    subprojects.append(subproject)
        
        return subprojects
    
    @staticmethod
    def _parse_requirements(req_file: Path) -> Dict[str, Package]:
        """Parse requirements.txt file into package-version dictionary."""
        requirements = {}
        with open(req_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    try:
                        package = Package.from_string(line)
                        requirements[package.name] = package
                    except Exception as e:
                        print(f"Error parsing line: {line}")
                        print(f"Error: {e}")
        return requirements

class VersionComparator:
    """Compares package versions between main project and subprojects."""
    
    @staticmethod
    def compare_versions(main_package: Package, sub_package: Package) -> bool:
        """Compare if versions are significantly different."""
        if not main_package.version or not sub_package.version:
            return False
            
        try:
            # If main project has an exact version, check if subproject's version is compatible
            if main_package.version.specifier == VersionSpecifier.EXACT:
                return not sub_package.version.is_compatible_with(main_package.version.version)
            
            # If main project has a range, check if subproject's version falls within it
            return not main_package.version.is_compatible_with(sub_package.version.version)
        except version.InvalidVersion:
            return False

class GitHubCommitChecker:
    """Checks Git commit dates for subprojects."""
    
    @staticmethod
    def get_last_commit_date(repo_path: Path) -> Optional[datetime]:
        """Get the last commit date for a Git repository using local operations."""
        try:
            result = subprocess.run(
                ['git', 'log', '-1', '--format=%cI'],
                cwd=repo_path,
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                commit_date = result.stdout.strip()
                return datetime.fromisoformat(commit_date)
            return None
        except Exception as e:
            logger.warning(f"Error getting local commit date for {repo_path}: {str(e)}")
            return None

@dataclass
class OperationResult:
    """Represents the result of an operation in test mode."""
    success: bool
    message: str
    command: Optional[str] = None
    changes: List[str] = field(default_factory=list)
    project_name: Optional[str] = None

class TestModeManager:
    """Manages test mode operations and logging."""
    
    def __init__(self, enabled: bool = False, subprojects: List[SubprojectInfo] = None, root_path: Path = None):
        self.enabled = enabled
        self.operations: List[OperationResult] = []
        self.subprojects = subprojects or []
        self.root_path = root_path
    
    def log_operation(self, success: bool, message: str, command: Optional[str] = None, changes: List[str] = None, project_name: Optional[str] = None):
        """Log an operation and its result."""
        result = OperationResult(
            success=success,
            message=message,
            command=command,
            changes=changes or [],
            project_name=project_name
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
    
    def _analyze_package_conflicts(self) -> Tuple[Dict[str, List[Tuple[str, str]]], Dict[str, List[str]]]:
        """Analyze package installations for conflicts and unique installs."""
        # Dictionary to track package versions by project
        package_versions: Dict[str, Dict[str, str]] = {}
        # Dictionary to track unique packages (no version conflicts)
        unique_packages: Dict[str, List[str]] = {}
        
        for op in self.operations:
            if not op.success or not op.project_name:
                continue
                
            if "installed" in op.message.lower():
                # Extract package name and version from message
                # Format: "Installed package==version" or "Installed package"
                parts = op.message.split()
                if len(parts) >= 2:
                    package_spec = parts[1]
                    if '==' in package_spec:
                        package, version = package_spec.split('==', 1)
                    else:
                        package = package_spec
                        version = "any"
                    
                    # Track package version by project
                    if package not in package_versions:
                        package_versions[package] = {}
                    package_versions[package][op.project_name] = version
        
        # Analyze conflicts and unique packages
        conflicts: Dict[str, List[Tuple[str, str]]] = {}
        for package, versions in package_versions.items():
            if len(versions) > 1:
                # Check if all versions are the same
                unique_versions = set(versions.values())
                if len(unique_versions) > 1:
                    conflicts[package] = [(proj, ver) for proj, ver in versions.items()]
            else:
                # This is a unique package (only installed by one project)
                project = next(iter(versions.keys()))
                if project not in unique_packages:
                    unique_packages[project] = []
                unique_packages[project].append(package)
        
        return conflicts, unique_packages
    
    def get_summary(self) -> str:
        """Get a concise summary of all operations that would be performed."""
        logger.debug(f"Total operations: {len(self.operations)}")
        logger.debug(f"Operations: {self.operations}")
        
        # Group operations by project
        project_ops: Dict[str, List[OperationResult]] = {}
        for op in self.operations:
            if op.project_name:
                if op.project_name not in project_ops:
                    project_ops[op.project_name] = []
                project_ops[op.project_name].append(op)
        
        logger.debug(f"Projects with operations: {list(project_ops.keys())}")
        
        # Generate summary
        summary = ["\nTest Mode Summary:"]
        
        # Group projects by status
        success_projects = []
        warning_projects = []
        error_projects = []
        error_details = []  # Track detailed error information
        
        # Get project info for sorting
        project_info = {p.name: p for p in self.subprojects}
        logger.debug(f"Project info: {project_info}")
        
        for project, ops in project_ops.items():
            logger.debug(f"Processing project: {project}")
            # Skip main project in summary (only if it's the root project)
            if project_info.get(project) and project_info[project].path == self.root_path:
                logger.debug(f"Skipping main project: {project}")
                continue
                
            has_errors = any(not op.success for op in ops)
            has_warnings = any("warning" in op.message.lower() for op in ops)
            
            # Count successful installs
            install_count = sum(1 for op in ops if op.success and "installed" in op.message.lower())
            
            # Get Git status and operation
            git_status = None
            git_operation = None
            for op in ops:
                if op.success and ("pull" in op.message.lower() or "fetch" in op.message.lower()):
                    git_operation = "pull" if "pull" in op.message.lower() else "fetch"
                elif op.success and "status" in op.message.lower():
                    git_status = op.message.split(":")[-1].strip()
            
            # Get error from SubprojectInfo if any
            subproject_error = project_info.get(project, SubprojectInfo(None, None, project)).error
            
            if has_errors:
                error_msg = next(op for op in ops if not op.success).message
                error_projects.append((project, error_msg))
                # Add detailed error information if available from SubprojectInfo
                if subproject_error:
                    error_details.append((project, subproject_error))
            elif has_warnings:
                warning_projects.append((project, next(op for op in ops if 'warning' in op.message.lower()).message))
            else:
                success_projects.append((project, install_count, git_status, git_operation, subproject_error))
        
        logger.debug(f"Success projects: {success_projects}")
        logger.debug(f"Warning projects: {warning_projects}")
        logger.debug(f"Error projects: {error_projects}")
        
        # Sort projects by parent-child relationship, Git status, and name
        def sort_key(item):
            project_name = item[0]
            info = project_info.get(project_name)
            if not info:
                return (0, 4, "", project_name)  # Default sort for unknown projects
            
            # Get Git status from operations
            git_status = None
            for op in project_ops.get(project_name, []):
                if op.success and "status" in op.message.lower():
                    git_status = op.message.split(":")[-1].strip()
                    break
            
            # Sort by:
            # 1. Parent path (None first)
            # 2. Git status (clean first, then uncommitted changes, then unpushed commits)
            # 3. Project name
            parent_name = info.parent_path.name if info.parent_path else ""
            status_order = {
                "Repository is clean": 0,
                "Repository has uncommitted changes": 1,
                "Repository has unpushed commits": 2
            }
            git_status_order = status_order.get(git_status, 3) if git_status else 3
            
            return (parent_name, git_status_order, git_status or "", project_name)
        
        # Add sections to summary with column formatting
        if error_projects:
            summary.append("\nProjects with errors:")
            max_name_len = max(len(name) for name, _ in error_projects)
            summary.extend(f"  {name:<{max_name_len}}  {msg}" for name, msg in sorted(error_projects, key=sort_key))
        
        if warning_projects:
            summary.append("\nProjects with warnings:")
            max_name_len = max(len(name) for name, _ in warning_projects)
            summary.extend(f"  {name:<{max_name_len}}  {msg}" for name, msg in sorted(warning_projects, key=sort_key))
        
        if success_projects:
            summary.append("\nSuccessful projects:")
            max_name_len = max(len(name) for name, _, _, _, _ in success_projects) + 1
            max_pkg_len = max(len(str(install_count)) for _, install_count, _, _, _ in success_projects) + 1
            max_git_len = max(len(git_status or "") for _, _, git_status, _, _ in success_projects) + 1
            max_error_len = max(len(error or "") for _, _, _, _, error in success_projects) + 1
            
            # Add header
            summary.append(f"  {'Project':<{max_name_len}}  {'Pkgs':<{max_pkg_len}}  {'Git Status':<{max_git_len}}  {'Operation':<10}  {'Error':<{max_error_len}}")
            
            # Add each project
            for name, install_count, git_status, git_operation, error in sorted(success_projects, key=sort_key):
                install_count = str(install_count) if install_count else ""
                operation = f"({git_operation})" if git_operation else ""
                error = error.replace('\n', '\n' + ' ' * (max_name_len + 4)) if error else ""
                summary.append(f"  {name:<{max_name_len}}  {install_count:<{max_pkg_len}}  {git_status or '':<{max_git_len}}  {operation:<10}  {error or '':<{max_error_len}}")
        
        # Add package analysis
        conflicts, unique_packages = self._analyze_package_conflicts()
        
        if conflicts:
            summary.append("\nPackage version conflicts:")
            max_pkg_len = max(len(pkg) for pkg in conflicts.keys())
            for package, versions in conflicts.items():
                summary.append(f"  {package:<{max_pkg_len}}  {', '.join(f'{proj}:{ver}' for proj, ver in versions)}")
        
        if unique_packages:
            summary.append("\nUnique package installations:")
            max_proj_len = max(len(proj) for proj in unique_packages.keys())
            for project, packages in unique_packages.items():
                if packages:
                    summary.append(f"  {project:<{max_proj_len}}  {', '.join(sorted(packages))}")
        
        # Add detailed error information section
        if error_details:
            summary.append("\nDetailed Error Information:")
            max_name_len = max(len(name) for name, _ in error_details)
            for project, error in sorted(error_details, key=sort_key):
                # Format the error message to be more readable
                formatted_error = error.replace('\n', '\n' + ' ' * (max_name_len + 4))
                summary.append(f"  {project:<{max_name_len}}  {formatted_error}")
        
        return "\n".join(summary)

class GitManager:
    """Handles Git operations for subprojects."""
    
    # Common Python-specific patterns to ignore in Git status
    PYTHON_IGNORE_PATTERNS = [
        '*.pyc',
        '*.pyo',
        '*.pyd',
        '__pycache__/',
        '*.so',
        '*.egg-info/',
        '.pytest_cache/',
        '.mypy_cache/',
        '.coverage',
        'htmlcov/',
        '.tox/',
        '.eggs/',
        'build/',
        'dist/',
        '*.egg'
    ]
    
    def __init__(self, test_mode: TestModeManager):
        self.test_mode = test_mode
    
    def is_git_repo(self, path: Path) -> bool:
        """Check if a directory is a Git repository."""
        if self.test_mode.enabled:
            self.test_mode.log_operation(
                True,
                f"Checking if {path} is a Git repository",
                f"git rev-parse --is-inside-work-tree"
            )
            return True  # Assume it is for testing
            
        try:
            result = subprocess.run(
                ['git', 'rev-parse', '--is-inside-work-tree'],
                cwd=path,
                capture_output=True,
                text=True
            )
            return result.returncode == 0 and result.stdout.strip() == 'true'
        except Exception:
            return False
    
    def get_remote_url(self, path: Path) -> Optional[str]:
        """Get the remote URL for a Git repository."""
        if self.test_mode.enabled:
            self.test_mode.log_operation(
                True,
                f"Getting remote URL for {path}",
                f"git remote get-url origin"
            )
            return f"https://github.com/test/{path.name}.git"  # Simulated URL
            
        try:
            result = subprocess.run(
                ['git', 'remote', 'get-url', 'origin'],
                cwd=path,
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                url = result.stdout.strip()
                if url.startswith('git@github.com:'):
                    url = url.replace('git@github.com:', 'https://github.com/')
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
                "git checkout -- ."
            )
            return
            
        try:
            # Restore modified/deleted files to their tracked state
            subprocess.run(
                ['git', 'checkout', '--', '.'],
                cwd=path,
                capture_output=True,
                text=True
            )
            
            # Get list of tracked files
            tracked_result = subprocess.run(
                ['git', 'ls-files'],
                cwd=path,
                capture_output=True,
                text=True
            )
            
            if tracked_result.returncode != 0:
                logger.warning(f"Failed to get tracked files: {tracked_result.stderr}")
                return
                
            # Create set of tracked files with both path separator variants
            tracked_files = set()
            for file in tracked_result.stdout.strip().split('\n'):
                if file:
                    tracked_files.add(file)
                    tracked_files.add(file.replace('/', '\\'))
            
            # Additionally, explicitly clean common Python artifacts that might not be in .gitignore
            for pattern in self.PYTHON_IGNORE_PATTERNS:
                # Handle directory patterns (ending with /)
                if pattern.endswith('/'):
                    dir_pattern = pattern.rstrip('/')
                    for dir_path in path.rglob(dir_pattern):
                        if dir_path.is_dir():
                            # Check if any files in the directory are tracked
                            has_tracked_files = False
                            for file_path in dir_path.rglob('*'):
                                if file_path.is_file():
                                    rel_path = str(file_path.relative_to(path))
                                    if rel_path in tracked_files or rel_path.replace('\\', '/') in tracked_files:
                                        has_tracked_files = True
                                        break
                                        
                            if not has_tracked_files:
                                try:
                                    import shutil
                                    shutil.rmtree(dir_path)
                                    logger.info(f"Removed directory: {dir_path}")
                                except Exception as e:
                                    logger.warning(f"Failed to remove directory {dir_path}: {str(e)}")
                # Handle file patterns
                else:
                    for file_path in path.rglob(pattern):
                        if file_path.is_file():
                            rel_path = str(file_path.relative_to(path))
                            if rel_path not in tracked_files and rel_path.replace('\\', '/') not in tracked_files:
                                try:
                                    file_path.unlink()
                                    logger.info(f"Removed file: {file_path}")
                                except Exception as e:
                                    logger.warning(f"Failed to remove file {file_path}: {str(e)}")
        except Exception as e:
            logger.warning(f"Warning: Failed to restore files: {str(e)}")
    
    def _is_ignored_change(self, status_line: str) -> bool:
        """Check if a Git status line should be ignored."""
        # Git status format: XY filename
        # X = index status, Y = working tree status
        if len(status_line) < 3:
            logger.debug(f"Status line too short: {status_line}")
            return False
            
        # Get both index and working tree status
        index_status = status_line[0]
        working_status = status_line[1]
        filename = status_line[3:].strip()  # Get filename
        
        logger.debug(f"Checking status line: {status_line}")
        logger.debug(f"Index status: {index_status}, Working status: {working_status}, Filename: {filename}")
        
        # If file is untracked (??) or modified (M), check if it matches ignore patterns
        if working_status in ['?', 'M'] or index_status in ['M', 'A']:
            for pattern in self.PYTHON_IGNORE_PATTERNS:
                matches = (
                    filename.endswith(pattern.rstrip('/')) or  # For files
                    (pattern.endswith('/') and filename.startswith(pattern))  # For directories
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
                ['git', 'status', '--porcelain'],
                cwd=path,
                capture_output=True,
                text=True
            )
            
            if status_result.returncode != 0:
                return False, "Failed to get Git status", False
            
            # Get raw status lines before filtering
            raw_status_lines = status_result.stdout.strip().split('\n')
            logger.debug(f"Raw Git status lines: {raw_status_lines}")
            
            # Filter out ignored changes
            relevant_changes = []
            for line in raw_status_lines:
                if line:  # Skip empty lines
                    logger.debug(f"Processing status line: {line}")
                    if not self._is_ignored_change(line):
                        relevant_changes.append(line)
                        logger.debug(f"Added to relevant changes: {line}")
            
            # Track if we filtered out any changes
            was_cleaned_by_filtering = len(raw_status_lines) > len(relevant_changes)
            
            if relevant_changes:
                logger.debug(f"Found relevant changes: {relevant_changes}")
                return False, "Repository has uncommitted changes", was_cleaned_by_filtering
            
            unpushed_result = subprocess.run(
                ['git', 'cherry', '-v'],
                cwd=path,
                capture_output=True,
                text=True
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
            # Only log if there would be actual changes
            if not is_clean or "up to date" not in status_msg.lower():
                operation = "pull" if is_clean else "fetch"
                self.test_mode.log_operation(
                    True,
                    f"Would {operation} changes for {path}",
                    f"git {operation}",
                    [f"Update repository at {path}"]
                )
                return True, f"Would {operation} changes"
            return True, "Repository up to date"
            
        try:
            if is_clean:
                # Only clean Python artifacts if the repository was cleaned by our filtering
                if was_cleaned_by_filtering:
                    self._clean_python_artifacts(path)
                
                # Double-check status after cleaning
                is_clean_after, status_after, _ = self.get_git_status(path)
                if not is_clean_after:
                    logger.warning(f"Repository still not clean after cleaning artifacts: {status_after}")
                    return False, f"Repository not clean: {status_after}"
                
                pull_result = subprocess.run(
                    ['git', 'pull'],
                    cwd=path,
                    capture_output=True,
                    text=True
                )
                if pull_result.returncode == 0:
                    changes = pull_result.stdout.strip()
                    if changes:
                        return True, f"Pulled changes: {changes}"
                    return True, "Repository up to date"
                return False, f"Failed to pull changes: {pull_result.stderr.strip()}"
            else:
                # For non-clean repositories, just fetch
                fetch_result = subprocess.run(
                    ['git', 'fetch'],
                    cwd=path,
                    capture_output=True,
                    text=True
                )
                if fetch_result.returncode == 0:
                    return True, "Fetched changes (repository not clean)"
                return False, f"Failed to fetch changes: {fetch_result.stderr.strip()}"
        except Exception as e:
            return False, f"Error updating repository: {str(e)}"

class PipInstaller:
    """Handles pip installation in the correct virtual environment."""
    
    def __init__(self, test_mode: TestModeManager):
        self.test_mode = test_mode
    
    def install_requirements(self, requirements_file: Path, env_path: Path) -> Tuple[bool, Optional[str]]:
        """Install packages from a requirements.txt file.
        
        Returns:
            Tuple[bool, Optional[str]]: (success, error_message)
            success is True if the packages were installed or already satisfied
            error_message is None if successful, or contains the error message if failed
        """
        pip_cmd = [str(env_path / 'Scripts' / 'pip' if os.name == 'nt' else env_path / 'bin' / 'pip'), 'install', '-r', str(requirements_file)]
            
        if self.test_mode.enabled:
            self.test_mode.log_operation(
                True,
                f"Would install requirements from {requirements_file}",
                ' '.join(pip_cmd),
                [f"Install requirements from {requirements_file}"]
            )
            return True, None
            
        try:
            result = subprocess.run(pip_cmd, capture_output=True, text=True)
            
            # Check if the packages were installed or already satisfied
            if result.returncode == 0:
                return True, None
                
            # Check if the error is just a warning about dependency conflicts
            stderr = result.stderr.lower()
            if any(warning in stderr for warning in [
                "already satisfied",
                "requirement already satisfied",
                "dependency conflict",
                "conflicting dependencies",
                "version conflict",
                "incompatible dependencies"
            ]):
                return True, None
                
            # If we get here, it's a real error
            return False, result.stderr.strip()
            
        except Exception as e:
            return False, str(e)
    
    def install_package(self, package: str, version: Optional[str], env_path: Path) -> Tuple[bool, Optional[str]]:
        """Install a single package in the specified virtual environment.
        
        This is used as a fallback when requirements.txt installation fails.
        
        Returns:
            Tuple[bool, Optional[str]]: (success, error_message)
            success is True if the package was installed or already satisfied
            error_message is None if successful, or contains the error message if failed
        """
        pip_cmd = [str(env_path / 'Scripts' / 'pip' if os.name == 'nt' else env_path / 'bin' / 'pip'), 'install', f"{package}=={version}" if version else package]
            
        if self.test_mode.enabled:
            self.test_mode.log_operation(
                True,
                f"Would install package: {package}{'==' + version if version else ''}",
                ' '.join(pip_cmd),
                [f"Install {package} in virtual environment"]
            )
            return True, None
            
        try:
            result = subprocess.run(pip_cmd, capture_output=True, text=True)
            
            # Check if the package was installed or already satisfied
            if result.returncode == 0:
                return True, None
                
            # Check if the error is just a warning about dependency conflicts
            stderr = result.stderr.lower()
            if any(warning in stderr for warning in [
                "already satisfied",
                "requirement already satisfied",
                "dependency conflict",
                "conflicting dependencies",
                "version conflict",
                "incompatible dependencies"
            ]):
                return True, None
                
            # If we get here, it's a real error
            return False, result.stderr.strip()
            
        except Exception as e:
            return False, str(e)

class SubprojectManager:
    """Main orchestrator class for managing subproject installations."""
    
    def __init__(self, root_path: Path, env_path: Path, test_mode: bool = False, git_only: bool = False, max_depth: int = 2):
        self.root_path = root_path
        self.env_path = env_path
        self.ignored_subprojects = set()
        self.test_mode = TestModeManager(test_mode, root_path=root_path)
        self.git_manager = GitManager(self.test_mode)
        self.pip_installer = PipInstaller(self.test_mode)
        self.git_only = git_only
        self.max_depth = max_depth
        
        # TODO: Add main project handling
        # The main project should be handled separately from subprojects:
        # 1. Before subproject analysis:
        #    - Check main project's Git status
        #    - Update main project if needed
        #    - Clean main project's Python artifacts
        # 2. After subproject analysis:
        #    - Install main project's requirements
        #    - Verify all dependencies are compatible
        
    def set_ignored_subprojects(self, subproject_names: List[str]):
        """Set which subprojects to ignore."""
        self.ignored_subprojects = set(subproject_names)

    def run(self):
        """Main method to run the subproject manager."""
        # TODO: Add main project pre-processing here
        # self.process_main_project_pre()
        
        # Process subprojects
        self.process_subprojects()
        
        # TODO: Add main project post-processing here
        # self.process_main_project_post()
        
        # Always show summary, not just in test mode
        print(self.test_mode.get_summary())

    def process_subprojects(self):
        """Main method to process all subprojects."""
        
        subprojects = SubprojectFinder.find_subprojects(self.root_path, self.max_depth)
        self.test_mode.subprojects = subprojects  # Update test mode with subprojects
        
        for subproject in subprojects:
            if subproject.name in self.ignored_subprojects:
                logger.info(f"Skipping ignored subproject: {subproject.name}")
                continue
                
            try:
                self.process_subproject(subproject)
            except Exception as e:
                logger.error(f"Error processing subproject {subproject.name}: {str(e)}")
                raise

    def process_subproject(self, subproject: SubprojectInfo):
        """Process a single subproject."""
        logger.info(f"\nProcessing subproject: {subproject.name}")
        
        try:
            # Check if this is a Git repository and get its URL
            if self.git_manager.is_git_repo(subproject.path):
                # Get and set the GitHub URL
                github_url = self.git_manager.get_remote_url(subproject.path)
                if github_url:
                    subproject.github_url = github_url
                    logger.info(f"GitHub URL: {github_url}")
                
                # Get Git status
                is_clean, status_msg, was_cleaned_by_filtering = self.git_manager.get_git_status(subproject.path)
                logger.info(f"Git status: {status_msg}")
                self.test_mode.log_operation(
                    True,
                    f"Git status: {status_msg}",
                    project_name=subproject.name
                )
                
                # Update the repository
                success, message = self.git_manager.update_repository(subproject.path)
                if not success:
                    logger.warning(f"Warning: Git update failed for {subproject.name}")
                    self.test_mode.log_operation(
                        False,
                        f"Git update failed: {message}",
                        project_name=subproject.name
                    )
                    subproject.error = f"Git update failed: {message}"
                    return
                elif "up to date" not in message.lower():
                    logger.info(message)
                    self.test_mode.log_operation(
                        True,
                        message,
                        project_name=subproject.name
                    )
                else:
                    self.test_mode.log_operation(
                        True,
                        "Repository up to date",
                        project_name=subproject.name
                    )
                
                # Get local commit date
                last_commit = GitHubCommitChecker.get_last_commit_date(subproject.path)
                if last_commit:
                    logger.info(f"Last commit date: {last_commit}")
                    subproject.last_commit_date = last_commit
                else:
                    logger.info(f"Could not determine last commit date for {subproject.name}")
            
            # Skip pip installations if git_only is True
            if self.git_only:
                logger.info("Skipping pip installations (--git-only mode)")
                return

            failed_packages = []

            # Process requirements
            for package_name, package in subproject.requirements.items():
                if package.version:
                    success, error = self.pip_installer.install_package(package_name, str(package.version), self.env_path)
                    if success:
                        logger.info(f"Installed {package}")
                        self.test_mode.log_operation(
                            True,
                            f"Installed {package}",
                            project_name=subproject.name
                        )
                    else:
                        logger.warning(f"Failed to install {package}: {error}")
                        self.test_mode.log_operation(
                            False,
                            f"Failed to install {package}: {error}",
                            project_name=subproject.name
                        )
                        failed_packages.append(package)
                else:
                    success, error = self.pip_installer.install_package(package_name, None, self.env_path)
                    if success:
                        logger.info(f"Installed {package_name}")
                        self.test_mode.log_operation(
                            True,
                            f"Installed {package_name}",
                            project_name=subproject.name
                        )
                    else:
                        logger.warning(f"Failed to install {package_name}: {error}")
                        self.test_mode.log_operation(
                            False,
                            f"Failed to install {package_name}: {error}",
                            project_name=subproject.name
                        )
                        failed_packages.append(package_name)

            if failed_packages:
                error_msg = f"Failed to install packages: {', '.join(str(p) for p in failed_packages)}"
                logger.warning(error_msg)
                subproject.error = error_msg

        except Exception as e:
            error_msg = f"Error processing subproject: {str(e)}"
            logger.error(error_msg)
            subproject.error = error_msg
            self.test_mode.log_operation(
                False,
                error_msg,
                project_name=subproject.name
            )


def main():
    # Set up argument parser
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root-path', type=Path, required=True,
        help='Root directory of the project to process (required)')
    parser.add_argument('--env-path', type=Path, required=True,
        help='Path to the conda environment (required)')
    parser.add_argument('--execute', action='store_true',
        help='Execute actual changes (default is test mode - no changes will be made)')
    parser.add_argument('--git-only', action='store_true',
        help='Only perform Git operations, skip pip installations')
    parser.add_argument('--max-depth', type=int, default=3,
        help='Maximum depth to search for requirements files')
    parser.add_argument('--ignore', nargs='+',
        default=['venv', '.git', 'tests', 'tests-unit', 'tests-integration', 'tests-functional'],
        help='List of subproject names to ignore')
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], default='INFO',
        help='Set the logging level')
    parser.add_argument('--log-file', type=Path,
        help='Path to log file (if not specified, logs to console only)')
    
    # Parse arguments
    args = parser.parse_args()
    
    # Validate environment path
    if not args.env_path.exists():
        raise ValueError(f"Please provide a valid Python virtual environment path: {args.env_path}")
    
    # Check for Python executable
    python_exe = args.env_path / 'python.exe' if os.name == 'nt' else args.env_path / 'bin' / 'python'
    if not python_exe.exists():
        raise ValueError(f"Python executable not found in environment: {python_exe}")
    
    # Verify Python version
    try:
        result = subprocess.run([str(python_exe), '--version'], capture_output=True, text=True)
        if result.returncode != 0:
            raise ValueError(f"Failed to get Python version: {result.stderr}")
        logger.info(f"Using Python: {result.stdout.strip()}")
    except Exception as e:
        raise ValueError(f"Failed to verify Python installation: {str(e)}")
    
    # Create default log file if none specified
    if args.log_file is None:
        main_project_name = args.root_path.name
        args.log_file = Path(f"composite_project_pip_install_{main_project_name}.log")
    
    # Configure logging based on arguments
    log_handlers = [logging.StreamHandler()]
    if args.log_file:
        log_handlers.append(logging.FileHandler(args.log_file))
    
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=log_handlers
    )
    
    logger.info(f"Starting subproject manager with root path: {args.root_path}")
    logger.info(f"Using conda environment: {args.env_path}")
    logger.info(f"Mode: {'EXECUTE' if args.execute else 'TEST'} (no changes will be made)")
    logger.info(f"Git only mode: {'enabled' if args.git_only else 'disabled'}")
    logger.info(f"Maximum depth for requirements files: {args.max_depth}")
    logger.info(f"Log file: {args.log_file}")
    if args.ignore:
        logger.info(f"Ignoring subprojects: {', '.join(args.ignore)}")
    
    try:
        # Create and run the manager
        manager = SubprojectManager(
            root_path=args.root_path,
            env_path=args.env_path,
            test_mode=not args.execute,  # Invert execute to get test mode
            git_only=args.git_only,
            max_depth=args.max_depth
        )
        manager.set_ignored_subprojects(args.ignore)
        manager.run()
    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")
        raise

if __name__ == "__main__":
    main()
