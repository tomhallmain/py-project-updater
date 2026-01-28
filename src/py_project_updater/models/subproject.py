"""SubprojectInfo and OperationResult models."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from py_project_updater.models.package import Package


@dataclass
class SubprojectInfo:
    """Represents information about a subproject."""

    path: Optional[Path]
    requirements_file: Optional[Path]
    name: str
    github_url: Optional[str] = None
    last_commit_date: Optional[datetime] = None
    requirements: Dict[str, Package] = field(default_factory=dict)
    depth: int = 0
    parent_path: Optional[Path] = None
    is_nested: bool = False
    error: Optional[str] = None


@dataclass
class OperationResult:
    """Represents the result of an operation in test mode."""

    success: bool
    message: str
    command: Optional[str] = None
    changes: List[str] = field(default_factory=list)
    project_name: Optional[str] = None
