"""Git commit date checking for subprojects."""

import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class GitHubCommitChecker:
    """Checks Git commit dates for subprojects."""

    @staticmethod
    def get_last_commit_date(repo_path: Path) -> Optional[datetime]:
        """Get the last commit date for a Git repository using local operations."""
        try:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%cI"],
                cwd=repo_path,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                commit_date = result.stdout.strip()
                return datetime.fromisoformat(commit_date)
            return None
        except Exception as e:
            logger.warning(f"Error getting local commit date for {repo_path}: {str(e)}")
            return None
