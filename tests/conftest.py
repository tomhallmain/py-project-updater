"""Shared fixtures for py_project_updater tests."""

from pathlib import Path

import pytest

from py_project_updater.reporting import RunReporter


@pytest.fixture
def tmp_root(tmp_path: Path) -> Path:
    """A temporary directory used as project root."""
    return tmp_path


@pytest.fixture
def test_mode_manager() -> RunReporter:
    """RunReporter with test mode enabled (no real subprocess calls)."""
    return RunReporter(enabled=True)
