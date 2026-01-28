"""Tests for VersionComparator.compare_versions."""

import pytest

from py_project_updater.models import Package, VersionSpecifier
from py_project_updater.models.version import Version
from py_project_updater.services.version_comparator import VersionComparator


def _pkg(name: str, spec: VersionSpecifier, ver: str) -> Package:
    return Package(name=name, version=Version(specifier=spec, version=ver))


class TestVersionComparator:
    """Tests for compare_versions (exact vs range specifiers)."""

    def test_no_main_version_returns_false(self):
        main = Package("foo", version=None)
        sub = _pkg("foo", VersionSpecifier.EXACT, "1.0.0")
        assert VersionComparator.compare_versions(main, sub) is False

    def test_no_sub_version_returns_false(self):
        main = _pkg("foo", VersionSpecifier.EXACT, "1.0.0")
        sub = Package("foo", version=None)
        assert VersionComparator.compare_versions(main, sub) is False

    def test_exact_main_sub_same_not_significantly_different(self):
        main = _pkg("foo", VersionSpecifier.EXACT, "1.0.0")
        sub = _pkg("foo", VersionSpecifier.EXACT, "1.0.0")
        assert VersionComparator.compare_versions(main, sub) is False

    def test_exact_main_sub_different_significantly_different(self):
        main = _pkg("foo", VersionSpecifier.EXACT, "1.0.0")
        sub = _pkg("foo", VersionSpecifier.EXACT, "1.0.1")
        assert VersionComparator.compare_versions(main, sub) is True

    def test_main_greater_equal_sub_compatible_not_significantly_different(self):
        main = _pkg("foo", VersionSpecifier.GREATER_EQUAL, "1.0.0")
        sub = _pkg("foo", VersionSpecifier.EXACT, "1.2.0")
        # compare_versions: main not EXACT -> not main.is_compatible_with(sub.version.version)
        # main 1.0.0 >= vs sub 1.2.0: 1.0.0.is_compatible_with("1.2.0") -> other >= current -> True
        # So not significantly different -> False
        assert VersionComparator.compare_versions(main, sub) is False

    def test_main_greater_equal_sub_incompatible_significantly_different(self):
        main = _pkg("foo", VersionSpecifier.GREATER_EQUAL, "2.0.0")
        sub = _pkg("foo", VersionSpecifier.EXACT, "1.0.0")
        # main 2.0.0 >= .is_compatible_with("1.0.0") -> other >= current -> 1.0.0 >= 2.0.0 -> False
        assert VersionComparator.compare_versions(main, sub) is True

    def test_invalid_version_returns_false(self):
        main = _pkg("foo", VersionSpecifier.EXACT, "1.0.0")
        sub = _pkg("foo", VersionSpecifier.EXACT, "not.a.version")
        assert VersionComparator.compare_versions(main, sub) is False
