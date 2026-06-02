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
    DEFAULT_MAIN_WEIGHT,
    DEFAULT_MAX_DEPTH,
    DEFAULT_OUTLIER_THRESHOLD,
    DEFAULT_VERSION_TOLERANCE,
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

    if args.execute:
        python_exe = _get_python_exe(args.env_path)
        if _is_env_in_use(python_exe):
            logger.warning(
                "The Python environment appears to be in use by a running process. "
                "Pip installations may fail on locked extension modules. "
                "Consider stopping any running processes before proceeding."
            )

    if not _confirm_run(args):
        logger.info("Run cancelled.")
        return

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
            version_tolerance=args.version_tolerance,
            main_weight=args.main_weight,
            outlier_threshold=args.outlier_threshold,
        )
        ignore = set(DEFAULT_IGNORE) | set(args.ignore or [])
        manager.set_ignored_subprojects(list(ignore))
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
        "--version-tolerance",
        choices=["none", "patch", "minor"],
        default=DEFAULT_VERSION_TOLERANCE,
        help=(
            "How much version difference to tolerate before flagging a conflict. "
            "'none': flag any difference; "
            "'patch': allow matching patch versions (X.Y.*); "
            "'minor': allow matching major versions only (X.*.*). "
            f"Default: {DEFAULT_VERSION_TOLERANCE}"
        ),
    )
    p.add_argument(
        "--main-weight",
        type=float,
        default=DEFAULT_MAIN_WEIGHT,
        help=(
            "Weight given to the main project's version when computing the consensus "
            "for outlier detection (0–1, remainder shared equally across subprojects). "
            f"Default: {DEFAULT_MAIN_WEIGHT}"
        ),
    )
    p.add_argument(
        "--outlier-threshold",
        type=float,
        default=DEFAULT_OUTLIER_THRESHOLD,
        help=(
            "Number of weighted standard deviations below the consensus mean at which "
            "a subproject's package requirement is treated as an outlier and skipped. "
            f"Default: {DEFAULT_OUTLIER_THRESHOLD}"
        ),
    )
    p.add_argument(
        "--ignore",
        nargs="+",
        default=[],
        help="Additional subproject names to ignore (always combined with built-in defaults)",
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


def _get_python_exe(env_path: Path) -> Path:
    """Return the path to the Python executable for the given environment.

    On Windows, checks both the standard venv location (Scripts\\python.exe)
    and the conda layout (python.exe at the env root), returning whichever exists.
    """
    if os.name == "nt":
        for candidate in [
            env_path / "Scripts" / "python.exe",  # standard venv / virtualenv
            env_path / "python.exe",               # conda on Windows
        ]:
            if candidate.exists():
                return candidate
        return env_path / "Scripts" / "python.exe"  # fallback for error reporting
    return env_path / "bin" / "python"


def _validate_env(env_path: Path) -> None:
    """Ensure env_path exists and contains a valid Python executable."""
    if not env_path.exists():
        raise ValueError(f"Please provide a valid Python virtual environment path: {env_path}")

    python_exe = _get_python_exe(env_path)
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


def _is_env_in_use(python_exe: Path) -> bool:
    """Return True if any running process is using the given Python executable.

    Uses psutil when available (most reliable, all platforms). Falls back to
    platform-specific approaches: /proc scan on Linux, lsof on macOS,
    exclusive-open attempt on Windows.
    """
    target = python_exe.resolve()
    try:
        import psutil
        for proc in psutil.process_iter(["exe"]):
            try:
                if proc.info["exe"] and Path(proc.info["exe"]).resolve() == target:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return False
    except ImportError:
        pass

    if sys.platform == "linux":
        for pid_dir in Path("/proc").iterdir():
            if not pid_dir.name.isdigit():
                continue
            try:
                if (pid_dir / "exe").resolve() == target:
                    return True
            except OSError:
                pass
        return False

    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["lsof", "-w", str(target)],
                capture_output=True,
                text=True,
            )
            return bool(result.stdout.strip())
        except FileNotFoundError:
            return False

    # Windows fallback: try opening the executable for writing.
    # This is a best-effort check — it can produce false negatives since
    # Windows does not always lock the .exe itself, only loaded DLLs.
    try:
        with open(target, "r+b"):
            return False
    except PermissionError:
        return True
    except OSError:
        return False


def _confirm_run(args: argparse.Namespace) -> bool:
    """Prompt the user to confirm before running in either mode.

    Returns True to proceed, False to cancel. Skips the prompt and returns
    True automatically when stdin is not a terminal (scripts, CI).
    """
    if not sys.stdin.isatty():
        logger.info("Non-interactive session — skipping confirmation.")
        return True

    if args.execute:
        print("\nAbout to run in EXECUTE mode. The following changes will be made:")
        print(f"  Root path  : {args.root_path}")
        print(f"  Environment: {args.env_path}")
        if args.git_only:
            print("  Git operations only (no pip installations)")
        else:
            print("  Git repositories will be updated")
            print("  Packages will be installed into the environment")
    else:
        print("\nAbout to run in TEST mode. No changes will be made.")
        print(f"  Root path  : {args.root_path}")
        print(f"  Environment: {args.env_path}")
        print("  Git status will be checked (read-only)")
        print("  A summary of what would happen will be shown")
    print()

    try:
        answer = input("Proceed? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False

    return answer in ("y", "yes")


def _configure_logging(
    level: str = "INFO",
    log_file: Optional[Path] = None,
) -> None:
    """Configure logging to console and optionally to a file.

    Configures the root logger directly rather than using basicConfig, which
    is a no-op when handlers are already present (e.g. when launched as a
    console script entry point).
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level))
    root.handlers.clear()

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    if log_file is not None:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(formatter)
        root.addHandler(fh)
