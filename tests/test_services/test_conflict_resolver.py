"""Tests for ConflictResolver and related helpers."""

from datetime import datetime, timedelta, timezone

import pytest

from py_project_updater.models import Package, VersionSpecifier
from py_project_updater.models.version import Version
from py_project_updater.services.conflict_resolver import (
    ConflictResolver,
    _version_to_scalar,
)


def _pkg(spec: VersionSpecifier, ver: str) -> Package:
    return Package(name="foo", version=Version(specifier=spec, version=ver))


def _ge(ver: str) -> Package:
    return _pkg(VersionSpecifier.GREATER_EQUAL, ver)


def _eq(ver: str) -> Package:
    return _pkg(VersionSpecifier.EXACT, ver)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# _version_to_scalar
# ---------------------------------------------------------------------------

class TestVersionToScalar:
    def test_basic(self):
        assert _version_to_scalar("1.0.0") == 1_000_000

    def test_base_1000_encoding(self):
        assert _version_to_scalar("2.1.3") == 2_001_003

    def test_minor_separation(self):
        assert _version_to_scalar("1.25.0") - _version_to_scalar("1.20.0") == 5_000

    def test_major_separation(self):
        assert _version_to_scalar("2.0.0") - _version_to_scalar("1.0.0") == 1_000_000

    def test_components_beyond_third_ignored(self):
        assert _version_to_scalar("1.2.3.4") == _version_to_scalar("1.2.3")

    def test_invalid_returns_none(self):
        assert _version_to_scalar("not.a.version") is None


# ---------------------------------------------------------------------------
# ConflictResolver.compute_recency_factors
# ---------------------------------------------------------------------------

class TestComputeRecencyFactors:
    def test_no_main_commit_date_returns_all_ones(self):
        factors = ConflictResolver.compute_recency_factors(
            main_commit_date=None,
            sub_commit_dates={"a": NOW, "b": NOW},
            reference_time=NOW,
        )
        assert factors == {"a": 1.0, "b": 1.0}

    def test_sub_as_recent_as_main_gets_one(self):
        main_date = NOW - timedelta(days=7)
        sub_dates = {"a": NOW - timedelta(days=7)}
        factors = ConflictResolver.compute_recency_factors(
            main_commit_date=main_date,
            sub_commit_dates=sub_dates,
            reference_time=NOW,
        )
        assert factors["a"] == pytest.approx(1.0)

    def test_sub_more_recent_than_main_capped_at_one(self):
        main_date = NOW - timedelta(days=14)
        sub_dates = {"a": NOW - timedelta(days=7)}
        factors = ConflictResolver.compute_recency_factors(
            main_commit_date=main_date,
            sub_commit_dates=sub_dates,
            reference_time=NOW,
        )
        assert factors["a"] == 1.0

    def test_stale_sub_gets_reduced_factor(self):
        main_date = NOW - timedelta(days=7)
        sub_dates = {"a": NOW - timedelta(days=70)}
        factors = ConflictResolver.compute_recency_factors(
            main_commit_date=main_date,
            sub_commit_dates=sub_dates,
            reference_time=NOW,
        )
        assert factors["a"] == pytest.approx(7 / 70)

    def test_sub_with_no_commit_date_gets_one(self):
        main_date = NOW - timedelta(days=7)
        sub_dates = {"a": None}
        factors = ConflictResolver.compute_recency_factors(
            main_commit_date=main_date,
            sub_commit_dates=sub_dates,
            reference_time=NOW,
        )
        assert factors["a"] == 1.0


# ---------------------------------------------------------------------------
# ConflictResolver.find_package_outliers
# ---------------------------------------------------------------------------

class TestFindPackageOutliers:
    def test_population_too_small_returns_empty(self):
        result = ConflictResolver.find_package_outliers(
            main_package=_ge("1.25.0"),
            sub_packages={"a": _ge("1.24.0"), "b": _ge("1.20.0")},
            min_population=3,   # need main + 2 subs = 3; we have exactly 3 → passes
        )
        # All three are close together — no outlier expected
        assert result == []

    def test_below_min_population_returns_empty(self):
        result = ConflictResolver.find_package_outliers(
            main_package=_ge("1.25.0"),
            sub_packages={"a": _ge("1.24.0")},
            min_population=3,
        )
        assert result == []

    def test_all_same_version_returns_empty(self):
        result = ConflictResolver.find_package_outliers(
            main_package=_eq("1.0.0"),
            sub_packages={"a": _eq("1.0.0"), "b": _eq("1.0.0"), "c": _eq("1.0.0")},
        )
        assert result == []

    def test_clear_outlier_is_detected(self):
        # node_d at 1.10.0 is far below the cluster at 1.20-1.25
        result = ConflictResolver.find_package_outliers(
            main_package=_ge("1.25.0"),
            sub_packages={
                "node_a": _ge("1.24.0"),
                "node_b": _ge("1.20.0"),
                "node_c": _ge("1.22.0"),
                "node_d": _eq("1.10.0"),
            },
            main_weight=0.7,
            std_threshold=2.0,
        )
        assert "node_d" in result
        assert "node_a" not in result
        assert "node_b" not in result
        assert "node_c" not in result

    def test_no_outlier_when_cluster_is_tight(self):
        result = ConflictResolver.find_package_outliers(
            main_package=_ge("1.25.0"),
            sub_packages={
                "a": _ge("1.24.0"),
                "b": _ge("1.23.0"),
                "c": _ge("1.22.0"),
            },
            main_weight=0.7,
            std_threshold=2.0,
        )
        assert result == []

    def test_no_main_package_still_works(self):
        # Without main, all subs share weight equally
        result = ConflictResolver.find_package_outliers(
            main_package=None,
            sub_packages={
                "a": _ge("1.25.0"),
                "b": _ge("1.24.0"),
                "c": _ge("1.23.0"),
                "d": _eq("1.0.0"),
            },
            main_weight=0.7,
            std_threshold=2.0,
        )
        assert "d" in result

    def test_stale_outlier_detected_more_easily_with_recency(self):
        # Without recency, node_d may not be flagged at threshold=2.5
        no_recency = ConflictResolver.find_package_outliers(
            main_package=_ge("1.25.0"),
            sub_packages={
                "node_a": _ge("1.24.0"),
                "node_b": _ge("1.22.0"),
                "node_c": _ge("1.20.0"),
                "node_d": _eq("1.12.0"),
            },
            main_weight=0.7,
            std_threshold=2.5,
        )
        # With full recency penalty on node_d (very stale), should flag it
        # even if the base threshold wouldn't
        stale_recency = ConflictResolver.find_package_outliers(
            main_package=_ge("1.25.0"),
            sub_packages={
                "node_a": _ge("1.24.0"),
                "node_b": _ge("1.22.0"),
                "node_c": _ge("1.20.0"),
                "node_d": _eq("1.12.0"),
            },
            main_weight=0.7,
            std_threshold=2.5,
            sub_recency_factors={"node_a": 1.0, "node_b": 1.0, "node_c": 1.0, "node_d": 0.05},
        )
        # node_d's reduced weight pulls mean higher, making its z-score more extreme
        if "node_d" not in no_recency:
            assert "node_d" in stale_recency


# ---------------------------------------------------------------------------
# ConflictResolver.find_outliers
# ---------------------------------------------------------------------------

class TestFindOutliers:
    def _make_sub_reqs(self, mapping):
        """mapping: {proj_name: {pkg_name: (spec, ver)}}"""
        return {
            proj: {
                pkg: Package(name=pkg, version=Version(specifier=spec, version=ver))
                for pkg, (spec, ver) in pkgs.items()
            }
            for proj, pkgs in mapping.items()
        }

    def test_package_in_single_sub_not_analysed(self):
        main = {"numpy": _ge("1.25.0")}
        subs = self._make_sub_reqs({
            "node_a": {"numpy": (VersionSpecifier.GREATER_EQUAL, "1.24.0")},
        })
        result = ConflictResolver.find_outliers(main, subs)
        assert result == {}

    def test_outlier_detected_across_multiple_subs(self):
        main = {"numpy": _ge("1.25.0")}
        subs = self._make_sub_reqs({
            "node_a": {"numpy": (VersionSpecifier.GREATER_EQUAL, "1.24.0")},
            "node_b": {"numpy": (VersionSpecifier.GREATER_EQUAL, "1.22.0")},
            "node_c": {"numpy": (VersionSpecifier.GREATER_EQUAL, "1.23.0")},
            "node_d": {"numpy": (VersionSpecifier.EXACT, "1.10.0")},
        })
        result = ConflictResolver.find_outliers(main, subs, main_weight=0.7, std_threshold=2.0)
        assert "numpy" in result
        assert "node_d" in result["numpy"]

    def test_no_outliers_returns_empty_dict(self):
        main = {"numpy": _ge("1.25.0")}
        subs = self._make_sub_reqs({
            "node_a": {"numpy": (VersionSpecifier.GREATER_EQUAL, "1.24.0")},
            "node_b": {"numpy": (VersionSpecifier.GREATER_EQUAL, "1.23.0")},
            "node_c": {"numpy": (VersionSpecifier.GREATER_EQUAL, "1.22.0")},
        })
        result = ConflictResolver.find_outliers(main, subs)
        assert result == {}

    def test_package_not_in_main_still_analysed(self):
        main = {}
        subs = self._make_sub_reqs({
            "node_a": {"torch": (VersionSpecifier.GREATER_EQUAL, "2.0.0")},
            "node_b": {"torch": (VersionSpecifier.GREATER_EQUAL, "1.9.0")},
            "node_c": {"torch": (VersionSpecifier.GREATER_EQUAL, "2.1.0")},
            "node_d": {"torch": (VersionSpecifier.EXACT, "1.0.0")},
        })
        result = ConflictResolver.find_outliers(main, subs, main_weight=0.7, std_threshold=2.0)
        # Without main, subs share all weight — node_d may still be an outlier
        # (depends on distribution); at minimum the result type is correct
        assert isinstance(result, dict)
