"""CLI for py_project_updater: argparse and main entrypoint."""

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from py_project_updater.config import (
    DEFAULT_IGNORE,
    DEFAULT_LOG_LEVEL,
    DEFAULT_MAX_DEPTH,
    default_log_file_for_root,
)
from py_project_updater.orchestration import SubprojectManager

logger = logging.getLogger(__name__)

_DOC = """
Composite Project Pip Installer

Manage pip installations across multiple Python subprojects:
- Find and process requirements.txt in subprojects
- Update Git repositories
- Install packages in the correct virtual environment
- Show what changes would be made (test mode)

Usage:
    python -m py_project_updater --root-path PATH --env-path PATH [options]

Required:
    --root-path PATH   Root directory containing subprojects
    --env-path PATH    Path to your Python virtual environment

Optional:
    --execute          Actually make changes (default: test mode)
    --git-only         Only perform Git operations, skip pip
    --max-depth N      Max depth to search for requirements (default: 3)
    --ignore NAME      Subproject names to ignore (repeatable)
    --log-level LEVEL  DEBUG|INFO|WARNING|ERROR|CRITICAL
    --log-file PATH    Log file path (default: py_project_updater_<root_name>.log)
"""


def main() -> None:
    """Parse arguments, validate env, configure logging, and run SubprojectManager."""
    parser = _make_parser()
    args = parser.parse_args()

    log_file = args.log_file or default_log_file_for_root(args.root_path)
    _configure_logging(level=args.log_level, log_file=log_file)
    _validate_env(args.env_path)

    logger.info("Starting subproject manager with root path: %s", args.root_path)
    logger.info("Using environment: %s", args.env_path)
    logger.info("Mode: %s", "EXECUTE" if args.execute else "TEST (no changes)")
    logger.info("Git only: %s", "enabled" if args.git_only else "disabled")
    logger.info("Max depth: %s", args.max_depth)
    logger.info("Log file: %s", log_file)
    if args.ignore:
        logger.info("Ignoring subprojects: %s", ", ".join(args.ignore))

    try:
        manager = SubprojectManager(
            root_path=args.root_path,
            env_path=args.env_path,
            test_mode=not args.execute,
            git_only=args.git_only,
            max_depth=args.max_depth,
        )
        manager.set_ignored_subprojects(args.ignore)
        manager.run()
    except Exception as e:
        logger.error("An error occurred: %s", e)
        raise


def _make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=_DOC.strip(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--root-path",
        type=Path,
        required=True,
        help="Root directory of the project to process",
    )
    p.add_argument(
        "--env-path",
        type=Path,
        required=True,
        help="Path to the Python virtual environment",
    )
    p.add_argument(
        "--execute",
        action="store_true",
        help="Execute changes (default is test mode)",
    )
    p.add_argument(
        "--git-only",
        action="store_true",
        help="Only perform Git operations, skip pip installations",
    )
    p.add_argument(
        "--max-depth",
        type=int,
        default=DEFAULT_MAX_DEPTH,
        help="Maximum depth to search for requirements files",
    )
    p.add_argument(
        "--ignore",
        nargs="+",
        default=DEFAULT_IGNORE,
        help="Subproject names to ignore",
    )
    p.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=DEFAULT_LOG_LEVEL,
        help="Logging level",
    )
    p.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Log file path (default: py_project_updater_<root_name>.log)",
    )
    return p


def _validate_env(env_path: Path) -> None:
    """Ensure env_path exists and contains a valid Python executable."""
    if not env_path.exists():
        raise ValueError(f"Please provide a valid Python virtual environment path: {env_path}")

    python_exe = (
        env_path / "Scripts" / "python.exe"
        if os.name == "nt"
        else env_path / "bin" / "python"
    )
    if not python_exe.exists():
        raise ValueError(f"Python executable not found in environment: {python_exe}")

    try:
        result = subprocess.run(
            [str(python_exe), "--version"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise ValueError(f"Failed to get Python version: {result.stderr}")
        logger.info("Using Python: %s", result.stdout.strip())
    except Exception as e:
        if isinstance(e, ValueError):
            raise
        raise ValueError(f"Failed to verify Python installation: {e!s}") from e


def _configure_logging(
    level: str = "INFO",
    log_file: Optional[Path] = None,
) -> None:
    """Configure logging to console and optionally to a file."""
    handlers: List[logging.Handler] = [logging.StreamHandler()]
    if log_file is not None:
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=handlers,
    )
