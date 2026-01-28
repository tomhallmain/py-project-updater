"""Tests for Package model and Package.from_string."""

import pytest

from py_project_updater.models.package import Package
from py_project_updater.models.version import Version, VersionSpecifier


class TestPackageFromString:
    """Tests for Package.from_string parsing."""

    def test_no_specifier_returns_package_without_version(self):
        pkg = Package.from_string("requests")
        assert pkg.name == "requests"
        assert pkg.version is None

    def test_no_specifier_strips_whitespace(self):
        pkg = Package.from_string("  requests  ")
        assert pkg.name == "requests"
        assert pkg.version is None

    def test_exact_version(self):
        pkg = Package.from_string("requests==2.28.0")
        assert pkg.name == "requests"
        assert pkg.version is not None
        assert pkg.version.specifier == VersionSpecifier.EXACT
        assert pkg.version.version == "2.28.0"

    def test_greater_equal_version(self):
        pkg = Package.from_string("numpy>=1.20")
        assert pkg.name == "numpy"
        assert pkg.version.specifier == VersionSpecifier.GREATER_EQUAL
        assert pkg.version.version == "1.20"

    def test_less_equal_version(self):
        pkg = Package.from_string("wheel<=1.0.0")
        assert pkg.name == "wheel"
        assert pkg.version.specifier == VersionSpecifier.LESS_EQUAL
        assert pkg.version.version == "1.0.0"

    def test_compatible_version(self):
        pkg = Package.from_string("pkg~=2.1.0")
        assert pkg.name == "pkg"
        assert pkg.version.specifier == VersionSpecifier.COMPATIBLE
        assert pkg.version.version == "2.1.0"

    def test_not_equal_version(self):
        pkg = Package.from_string("foo!=1.0.0")
        assert pkg.name == "foo"
        assert pkg.version.specifier == VersionSpecifier.NOT_EQUAL
        assert pkg.version.version == "1.0.0"

    def test_package_with_extra_whitespace(self):
        pkg = Package.from_string("  requests  >=  2.28.0  ")
        assert pkg.name == "requests"
        assert pkg.version.version == "2.28.0"

    def test_str_with_version(self):
        pkg = Package.from_string("requests==2.28.0")
        assert str(pkg) == "requests==2.28.0"

    def test_str_without_version(self):
        pkg = Package.from_string("requests")
        assert str(pkg) == "requests"


class TestPackageEdgeCases:
    """Edge cases and lines that have no specifier."""

    def test_empty_like_name_with_no_specifier(self):
        # Line with no known specifiers is treated as name only
        pkg = Package.from_string("some-package-name")
        assert pkg.name == "some-package-name"
        assert pkg.version is None

    def test_comment_in_line_included_in_version(self):
        # from_string does not strip comments; version is everything after ==
        pkg = Package.from_string("pkg==1.0  # comment")
        assert pkg.name == "pkg"
        assert pkg.version is not None
        assert pkg.version.version == "1.0  # comment"
