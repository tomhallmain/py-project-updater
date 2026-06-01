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

    def test_main_greater_equal_sub_exact_within_range_no_conflict(self):
        main = _pkg("foo", VersionSpecifier.GREATER_EQUAL, "1.0.0")
        sub = _pkg("foo", VersionSpecifier.EXACT, "1.2.0")
        assert VersionComparator.compare_versions(main, sub) is False

    def test_main_greater_equal_sub_exact_below_range_conflict(self):
        main = _pkg("foo", VersionSpecifier.GREATER_EQUAL, "2.0.0")
        sub = _pkg("foo", VersionSpecifier.EXACT, "1.0.0")
        assert VersionComparator.compare_versions(main, sub) is True

    def test_both_greater_equal_different_bounds_no_conflict(self):
        # >=1.25 and >=1.20: any version >=1.25 satisfies both — not a conflict.
        main = _pkg("foo", VersionSpecifier.GREATER_EQUAL, "1.25.0")
        sub = _pkg("foo", VersionSpecifier.GREATER_EQUAL, "1.20.0")
        assert VersionComparator.compare_versions(main, sub) is False

    def test_both_greater_equal_same_bound_no_conflict(self):
        main = _pkg("foo", VersionSpecifier.GREATER_EQUAL, "1.0.0")
        sub = _pkg("foo", VersionSpecifier.GREATER_EQUAL, "1.0.0")
        assert VersionComparator.compare_versions(main, sub) is False

    def test_both_less_equal_no_conflict(self):
        main = _pkg("foo", VersionSpecifier.LESS_EQUAL, "2.0.0")
        sub = _pkg("foo", VersionSpecifier.LESS_EQUAL, "1.5.0")
        assert VersionComparator.compare_versions(main, sub) is False

    def test_opposing_ranges_with_overlap_no_conflict(self):
        main = _pkg("foo", VersionSpecifier.GREATER_EQUAL, "1.0.0")
        sub = _pkg("foo", VersionSpecifier.LESS_EQUAL, "2.0.0")
        assert VersionComparator.compare_versions(main, sub) is False

    def test_opposing_ranges_no_overlap_conflict(self):
        main = _pkg("foo", VersionSpecifier.GREATER_EQUAL, "3.0.0")
        sub = _pkg("foo", VersionSpecifier.LESS_EQUAL, "2.0.0")
        assert VersionComparator.compare_versions(main, sub) is True

    def test_exact_tolerance_patch_same_major_minor_no_conflict(self):
        main = _pkg("foo", VersionSpecifier.EXACT, "1.25.0")
        sub = _pkg("foo", VersionSpecifier.EXACT, "1.25.2")
        assert VersionComparator.compare_versions(main, sub, tolerance="patch") is False

    def test_exact_tolerance_patch_different_minor_conflict(self):
        main = _pkg("foo", VersionSpecifier.EXACT, "1.25.0")
        sub = _pkg("foo", VersionSpecifier.EXACT, "1.26.0")
        assert VersionComparator.compare_versions(main, sub, tolerance="patch") is True

    def test_exact_tolerance_minor_same_major_no_conflict(self):
        main = _pkg("foo", VersionSpecifier.EXACT, "1.25.0")
        sub = _pkg("foo", VersionSpecifier.EXACT, "1.26.0")
        assert VersionComparator.compare_versions(main, sub, tolerance="minor") is False

    def test_exact_tolerance_minor_different_major_conflict(self):
        main = _pkg("foo", VersionSpecifier.EXACT, "1.0.0")
        sub = _pkg("foo", VersionSpecifier.EXACT, "2.0.0")
        assert VersionComparator.compare_versions(main, sub, tolerance="minor") is True

    def test_invalid_version_returns_false(self):
        main = _pkg("foo", VersionSpecifier.EXACT, "1.0.0")
        sub = _pkg("foo", VersionSpecifier.EXACT, "not.a.version")
        assert VersionComparator.compare_versions(main, sub) is False
