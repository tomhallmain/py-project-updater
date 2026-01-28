"""Defaults and config loading for py_project_updater."""

from pathlib import Path
from typing import List

# Defaults for CLI and behaviour (config file support can be added later)
DEFAULT_MAX_DEPTH = 3
DEFAULT_IGNORE: List[str] = [
    "venv",
    ".git",
    "tests",
    "tests-unit",
    "tests-integration",
    "tests-functional",
]
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_FILE_PREFIX = "py_project_updater"


def default_log_file_for_root(root_path: Path) -> Path:
    """Return the default log file path for a given root directory."""
    return Path(f"{DEFAULT_LOG_FILE_PREFIX}_{root_path.name}.log")
