"""Defaults and config loading for py_project_updater."""

from pathlib import Path
from typing import List

# Defaults for CLI and behaviour (config file support can be added later)
DEFAULT_MAX_DEPTH = 3
DEFAULT_VERSION_TOLERANCE = "minor"  # "none" | "patch" | "minor"
DEFAULT_MAIN_WEIGHT = 0.7        # fraction of weight given to the main project's version
DEFAULT_OUTLIER_THRESHOLD = 2.0  # standard deviations below mean to count as an outlier
DEFAULT_STASH_FILE_THRESHOLD = 0.10  # max ratio of changed/total tracked files before skipping stash
DEFAULT_STASH_LINE_THRESHOLD = 150   # max lines changed in any single file before skipping stash
DEFAULT_RECOVERY_DIR = Path("stash_recovery")
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
