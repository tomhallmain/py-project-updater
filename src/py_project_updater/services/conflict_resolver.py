"""Statistical outlier detection for package version conflicts across subprojects."""

import math
from datetime import datetime, timezone
from typing import Dict, List, Optional

from packaging import version as pkg_version

from py_project_updater.models import Package


def _version_to_scalar(version_str: str) -> Optional[float]:
    """Convert a version string to a scalar for numeric comparison.

    Encodes (major, minor, patch) in base 1000: 2.1.3 → 2_001_003.
    Components beyond the third are ignored. Returns None for unparseable strings.
    """
    try:
        v = pkg_version.Version(version_str)
        return sum(part * (1000 ** (2 - i)) for i, part in enumerate(v.release[:3]))
    except pkg_version.InvalidVersion:
        return None


class ConflictResolver:
    """Identifies outlier subprojects through weighted statistical analysis."""

    @staticmethod
    def compute_recency_factors(
        main_commit_date: Optional[datetime],
        sub_commit_dates: Dict[str, Optional[datetime]],
        reference_time: Optional[datetime] = None,
    ) -> Dict[str, float]:
        """Return {subproject_name: recency_factor} where factor is in (0, 1].

        factor = min(1.0, main_age / sub_age).

        A subproject committed more recently than (or at the same time as) the
        main project gets 1.0. One that is proportionally older gets less — so
        stale subprojects have less influence on the version consensus.

        If either commit date is unavailable, that subproject gets 1.0 (no penalty).
        """
        if reference_time is None:
            reference_time = datetime.now(timezone.utc)

        if main_commit_date is None:
            return {name: 1.0 for name in sub_commit_dates}

        # Ensure reference_time is timezone-aware for safe subtraction
        if reference_time.tzinfo is None:
            reference_time = reference_time.replace(tzinfo=timezone.utc)

        main_commit = main_commit_date
        if main_commit.tzinfo is None:
            main_commit = main_commit.replace(tzinfo=timezone.utc)

        main_age = (reference_time - main_commit).total_seconds()
        if main_age <= 0:
            return {name: 1.0 for name in sub_commit_dates}

        factors: Dict[str, float] = {}
        for name, commit_date in sub_commit_dates.items():
            if commit_date is None:
                factors[name] = 1.0
                continue
            sub_commit = commit_date
            if sub_commit.tzinfo is None:
                sub_commit = sub_commit.replace(tzinfo=timezone.utc)
            sub_age = (reference_time - sub_commit).total_seconds()
            factors[name] = 1.0 if sub_age <= 0 else min(1.0, main_age / sub_age)

        return factors

    @staticmethod
    def find_package_outliers(
        main_package: Optional[Package],
        sub_packages: Dict[str, Package],
        main_weight: float = 0.7,
        std_threshold: float = 2.0,
        min_population: int = 3,
        sub_recency_factors: Optional[Dict[str, float]] = None,
    ) -> List[str]:
        """Return subproject names whose version is a statistical outlier.

        A subproject is an outlier when its version number sits more than
        std_threshold weighted standard deviations below the weighted mean.
        The main project carries main_weight; each subproject shares the
        remaining weight equally, then scaled by its recency factor so that
        stale subprojects contribute less to the consensus.

        Returns [] when the population is smaller than min_population or when
        all version numbers are identical (std dev = 0).
        """
        scalars: Dict[str, float] = {}

        if main_package and main_package.version:
            s = _version_to_scalar(main_package.version.version)
            if s is not None:
                scalars["__main__"] = s

        for name, pkg in sub_packages.items():
            if pkg.version:
                s = _version_to_scalar(pkg.version.version)
                if s is not None:
                    scalars[name] = s

        n_subs = sum(1 for k in scalars if k != "__main__")

        if len(scalars) < min_population or n_subs == 0:
            return []

        sub_weight = (1.0 - main_weight) / n_subs
        weights: Dict[str, float] = {
            k: (main_weight if k == "__main__" else sub_weight) for k in scalars
        }

        # Scale subproject weights by recency and re-normalise
        if sub_recency_factors:
            for k in weights:
                if k != "__main__":
                    weights[k] *= sub_recency_factors.get(k, 1.0)
            total = sum(weights.values())
            if total > 0:
                weights = {k: v / total for k, v in weights.items()}

        mean = sum(scalars[k] * weights[k] for k in scalars)
        variance = sum(weights[k] * (scalars[k] - mean) ** 2 for k in scalars)
        std = math.sqrt(variance)

        if std == 0:
            return []

        return [
            name for name in scalars
            if name != "__main__" and (scalars[name] - mean) / std < -std_threshold
        ]

    @staticmethod
    def find_outliers(
        main_requirements: Dict[str, Package],
        sub_requirements: Dict[str, Dict[str, Package]],
        main_weight: float = 0.7,
        std_threshold: float = 2.0,
        min_population: int = 3,
        sub_recency_factors: Optional[Dict[str, float]] = None,
    ) -> Dict[str, List[str]]:
        """Return {package_name: [outlier_subproject_names]} for all shared packages.

        Only packages that appear in at least two subprojects are analysed —
        a package unique to one subproject has no population to compare against.
        """
        all_packages: set = set(main_requirements)
        for pkgs in sub_requirements.values():
            all_packages |= set(pkgs)

        results: Dict[str, List[str]] = {}
        for package_name in all_packages:
            sub_pkgs = {
                proj: pkgs[package_name]
                for proj, pkgs in sub_requirements.items()
                if package_name in pkgs
            }
            if len(sub_pkgs) < 2:
                continue

            outliers = ConflictResolver.find_package_outliers(
                main_package=main_requirements.get(package_name),
                sub_packages=sub_pkgs,
                main_weight=main_weight,
                std_threshold=std_threshold,
                min_population=min_population,
                sub_recency_factors=sub_recency_factors,
            )
            if outliers:
                results[package_name] = outliers

        return results
