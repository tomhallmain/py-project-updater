"""Tests for Version and VersionSpecifier models."""

import pytest

from py_project_updater.models.version import Version, VersionSpecifier


class TestVersionSpecifier:
    """Tests for VersionSpecifier enum."""

    def test_exact_value(self):
        assert VersionSpecifier.EXACT.value == "=="

    def test_greater_equal_value(self):
        assert VersionSpecifier.GREATER_EQUAL.value == ">="


class TestVersion:
    """Tests for Version.is_compatible_with and string representation."""

    def test_str_with_exact(self):
        v = Version(VersionSpecifier.EXACT, "1.2.3")
        assert str(v) == "==1.2.3"

    def test_str_with_greater_equal(self):
        v = Version(VersionSpecifier.GREATER_EQUAL, "2.0.0")
        assert str(v) == ">=2.0.0"

    def test_exact_same_version_compatible(self):
        v = Version(VersionSpecifier.EXACT, "1.2.3")
        assert v.is_compatible_with("1.2.3") is True

    def test_exact_different_version_incompatible(self):
        v = Version(VersionSpecifier.EXACT, "1.2.3")
        assert v.is_compatible_with("1.2.4") is False
        assert v.is_compatible_with("1.2.2") is False

    def test_greater_equal_meets_version_compatible(self):
        v = Version(VersionSpecifier.GREATER_EQUAL, "2.0.0")
        assert v.is_compatible_with("2.0.0") is True
        assert v.is_compatible_with("2.1.0") is True
        assert v.is_compatible_with("3.0.0") is True

    def test_greater_equal_below_version_incompatible(self):
        v = Version(VersionSpecifier.GREATER_EQUAL, "2.0.0")
        assert v.is_compatible_with("1.9.9") is False

    def test_less_equal_meets_version_compatible(self):
        v = Version(VersionSpecifier.LESS_EQUAL, "2.0.0")
        assert v.is_compatible_with("2.0.0") is True
        assert v.is_compatible_with("1.0.0") is True

    def test_less_equal_above_version_incompatible(self):
        v = Version(VersionSpecifier.LESS_EQUAL, "2.0.0")
        assert v.is_compatible_with("2.0.1") is False

    def test_greater_strictly_above_compatible(self):
        v = Version(VersionSpecifier.GREATER, "2.0.0")
        assert v.is_compatible_with("2.0.1") is True
        assert v.is_compatible_with("2.0.0") is False

    def test_less_strictly_below_compatible(self):
        v = Version(VersionSpecifier.LESS, "2.0.0")
        assert v.is_compatible_with("1.9.9") is True
        assert v.is_compatible_with("2.0.0") is False

    def test_compatible_tilde_equals_same_major(self):
        v = Version(VersionSpecifier.COMPATIBLE, "2.1.0")
        assert v.is_compatible_with("2.1.0") is True
        assert v.is_compatible_with("2.9.9") is True
        assert v.is_compatible_with("3.0.0") is False
        assert v.is_compatible_with("2.0.9") is False

    def test_not_equal_different_compatible(self):
        v = Version(VersionSpecifier.NOT_EQUAL, "2.0.0")
        assert v.is_compatible_with("2.0.1") is True
        assert v.is_compatible_with("1.9.9") is True
        assert v.is_compatible_with("2.0.0") is False

    def test_invalid_version_returns_false(self):
        v = Version(VersionSpecifier.EXACT, "1.2.3")
        assert v.is_compatible_with("not.a.version") is False

    def test_invalid_self_version_returns_false(self):
        v = Version(VersionSpecifier.EXACT, "not.a.version")
        assert v.is_compatible_with("1.2.3") is False
