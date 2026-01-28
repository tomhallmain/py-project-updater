"""SubprojectFinder: discover subprojects with requirements.txt or .git."""

import logging
from pathlib import Path
from typing import Dict, List, Optional

from py_project_updater.models import Package, SubprojectInfo

logger = logging.getLogger(__name__)


class SubprojectFinder:
    """Finds all subprojects with requirements.txt files or Git repositories."""

    @staticmethod
    def _create_subproject(
        path: Path,
        root_path: Path,
        max_depth: int,
        requirements_file: Optional[Path] = None,
    ) -> Optional[SubprojectInfo]:
        """Create a SubprojectInfo for a given path.

        Args:
            path: Subproject directory path.
            root_path: Project root path.
            max_depth: Maximum depth to search.
            requirements_file: Path to requirements.txt, if any.

        Returns:
            SubprojectInfo if valid, None if path should be skipped.
        """
        if any(part.startswith(".") for part in path.parts):
            return None

        depth = len(path.relative_to(root_path).parts)
        if depth > max_depth:
            return None

        parent_path: Optional[Path] = None
        is_nested = False
        for parent in path.parents:
            if parent == root_path:
                break
            if (parent / "requirements.txt").exists() or (parent / ".git").is_dir():
                parent_path = parent
                is_nested = True
                break

        subproject_name = path.name
        requirements = (
            SubprojectFinder._parse_requirements(requirements_file)
            if requirements_file
            else {}
        )
        return SubprojectInfo(
            path=path,
            requirements_file=requirements_file,
            name=subproject_name,
            requirements=requirements,
            depth=depth,
            parent_path=parent_path,
            is_nested=is_nested,
        )

    @staticmethod
    def find_subprojects(root_path: Path, max_depth: int = 2) -> List[SubprojectInfo]:
        """Find all subprojects with requirements.txt or Git repositories.

        Args:
            root_path: Root directory to search from.
            max_depth: Maximum depth to search (default: 2).
        """
        subprojects: List[SubprojectInfo] = []
        processed_paths: set = set()

        for git_dir in root_path.rglob(".git"):
            if git_dir.is_dir():
                subproject_path = git_dir.parent
                if subproject_path not in processed_paths:
                    processed_paths.add(subproject_path)
                    req_file = subproject_path / "requirements.txt"
                    subproject = SubprojectFinder._create_subproject(
                        subproject_path,
                        root_path,
                        max_depth,
                        req_file if req_file.exists() else None,
                    )
                    if subproject:
                        subprojects.append(subproject)

        for req_file in root_path.rglob("requirements.txt"):
            subproject_path = req_file.parent
            if subproject_path not in processed_paths:
                processed_paths.add(subproject_path)
                subproject = SubprojectFinder._create_subproject(
                    subproject_path, root_path, max_depth, req_file
                )
                if subproject:
                    subprojects.append(subproject)

        return subprojects

    @staticmethod
    def _parse_requirements(req_file: Path) -> Dict[str, Package]:
        """Parse a requirements.txt into a package name -> Package mapping."""
        requirements: Dict[str, Package] = {}
        with open(req_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    try:
                        pkg = Package.from_string(line)
                        requirements[pkg.name] = pkg
                    except Exception as e:
                        logger.warning("Error parsing line %r: %s", line, e)
        return requirements
