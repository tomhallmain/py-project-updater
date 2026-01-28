"""Tests for SubprojectFinder."""

from pathlib import Path

import pytest

from py_project_updater.services.finder import SubprojectFinder


class TestSubprojectFinder:
    """Tests for find_subprojects and _create_subproject behaviour."""

    def test_empty_root_returns_empty_list(self, tmp_root: Path):
        result = SubprojectFinder.find_subprojects(tmp_root, max_depth=2)
        assert result == []

    def test_finds_subproject_with_requirements_txt(self, tmp_root: Path):
        sub = tmp_root / "sub"
        sub.mkdir()
        (sub / "requirements.txt").write_text("requests==2.28.0\n", encoding="utf-8")
        result = SubprojectFinder.find_subprojects(tmp_root, max_depth=2)
        assert len(result) == 1
        assert result[0].name == "sub"
        assert result[0].path == sub
        assert result[0].requirements_file == sub / "requirements.txt"
        assert result[0].depth == 1
        assert "requests" in result[0].requirements
        assert str(result[0].requirements["requests"]) == "requests==2.28.0"

    def test_finds_subproject_with_git_only(self, tmp_root: Path):
        sub = tmp_root / "sub"
        sub.mkdir()
        (sub / ".git").mkdir()
        result = SubprojectFinder.find_subprojects(tmp_root, max_depth=2)
        assert len(result) == 1
        assert result[0].name == "sub"
        assert result[0].requirements_file is None
        assert result[0].requirements == {}

    def test_respects_max_depth(self, tmp_root: Path):
        # depth 1
        (tmp_root / "a").mkdir()
        (tmp_root / "a" / "requirements.txt").write_text("x\n", encoding="utf-8")
        # depth 2
        (tmp_root / "a" / "b").mkdir()
        (tmp_root / "a" / "b" / "requirements.txt").write_text("y\n", encoding="utf-8")
        # depth 3
        (tmp_root / "a" / "b" / "c").mkdir()
        (tmp_root / "a" / "b" / "c" / "requirements.txt").write_text("z\n", encoding="utf-8")

        result_depth2 = SubprojectFinder.find_subprojects(tmp_root, max_depth=2)
        names_depth2 = {s.name for s in result_depth2}
        assert "a" in names_depth2
        assert "b" in names_depth2
        assert "c" not in names_depth2

        result_depth3 = SubprojectFinder.find_subprojects(tmp_root, max_depth=3)
        names_depth3 = {s.name for s in result_depth3}
        assert "c" in names_depth3

    def test_skips_dot_dirs(self, tmp_root: Path):
        (tmp_root / ".hidden").mkdir()
        (tmp_root / ".hidden" / "requirements.txt").write_text("x\n", encoding="utf-8")
        (tmp_root / ".hidden" / ".git").mkdir()
        result = SubprojectFinder.find_subprojects(tmp_root, max_depth=2)
        assert len(result) == 0

    def test_deduplicates_by_path(self, tmp_root: Path):
        sub = tmp_root / "sub"
        sub.mkdir()
        (sub / "requirements.txt").write_text("x\n", encoding="utf-8")
        (sub / ".git").mkdir()
        result = SubprojectFinder.find_subprojects(tmp_root, max_depth=2)
        assert len(result) == 1

    def test_parses_requirements_with_comments_and_blanks(self, tmp_root: Path):
        sub = tmp_root / "sub"
        sub.mkdir()
        (sub / "requirements.txt").write_text(
            "# comment\nrequests>=2.0\n\nnumpy==1.24.0\n",
            encoding="utf-8",
        )
        result = SubprojectFinder.find_subprojects(tmp_root, max_depth=2)
        assert len(result) == 1
        assert "requests" in result[0].requirements
        assert "numpy" in result[0].requirements
        assert result[0].requirements["numpy"].version is not None
        assert result[0].requirements["numpy"].version.version == "1.24.0"
