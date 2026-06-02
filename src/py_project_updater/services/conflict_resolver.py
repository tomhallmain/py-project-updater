"""Statistical outlier detection for package version conflicts across subprojects."""

import logging
import math
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from packaging import version as pkg_version

from py_project_updater.models import Package
from py_project_updater.models.version import Version, VersionSpecifier
from py_project_updater.services.version_comparator import VersionComparator

logger = logging.getLogger(__name__)


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


_LOWER_BOUNDS = {VersionSpecifier.GREATER_EQUAL, VersionSpecifier.GREATER, VersionSpecifier.COMPATIBLE}
_UPPER_BOUNDS = {VersionSpecifier.LESS_EQUAL, VersionSpecifier.LESS}


def _pick_best_spec(
    packages: List[Package],
    main_package: Optional[Package] = None,
) -> Tuple[Optional[Version], List[str]]:
    """Return the most constrained Version from a list of Package specs, plus conflict warnings.

    Priority: exact pins (==) beat lower bounds (>=, >, ~=) which beat upper
    bounds (<, <=). Among same-priority specs, the numerically highest version
    is used for pins and lower bounds; the numerically lowest for upper bounds.
    Specs whose version string cannot be parsed are skipped.

    If main_package is provided, its spec is treated as authoritative: if the
    otherwise-winning candidate conflicts with main's spec, main's spec wins
    instead. All specs that conflict with the final winner are returned as
    human-readable warning strings.
    """
    versioned = [p.version for p in packages if p.version is not None]
    main_v = main_package.version if main_package else None

    def _safe_parse(v: Version):
        try:
            return pkg_version.parse(v.version)
        except pkg_version.InvalidVersion:
            return None

    def _best(vs, *, use_max: bool) -> Optional[Version]:
        candidates = [(v, _safe_parse(v)) for v in vs]
        valid = [(v, p) for v, p in candidates if p is not None]
        if not valid:
            return None
        chosen = max(valid, key=lambda x: x[1]) if use_max else min(valid, key=lambda x: x[1])
        return chosen[0]

    # --- Pass 1 + 2: select winner by priority, with main-project override ---
    main_override = False
    winner: Optional[Version] = None

    # Priority 1: main exact pin wins outright
    if main_v and main_v.specifier == VersionSpecifier.EXACT:
        winner = main_v
        main_override = True

    # Priority 2–5: best spec from all packages, then check against main
    if winner is None:
        pins = [v for v in versioned if v.specifier == VersionSpecifier.EXACT]
        candidate = _best(pins, use_max=True)

        if candidate is None:
            lowers = [v for v in versioned if v.specifier in _LOWER_BOUNDS]
            candidate = _best(lowers, use_max=True)

        if candidate is None:
            uppers = [v for v in versioned if v.specifier in _UPPER_BOUNDS]
            candidate = _best(uppers, use_max=False)

        if candidate is not None and main_package is not None and main_v is not None:
            cand_pkg = Package(name=main_package.name, version=candidate)
            if VersionComparator.compare_versions(main_package, cand_pkg):
                winner = main_v
                main_override = True
            else:
                winner = candidate
        else:
            winner = candidate

    # Fallback: if no winner yet and main has any spec, use it (e.g. package only in main)
    if winner is None and main_v is not None:
        winner = main_v
        main_override = True

    if winner is None:
        return None, []

    # --- Conflict warnings ---
    pkg_name = packages[0].name if packages else (main_package.name if main_package else "unknown")
    winner_pkg = Package(name=pkg_name, version=winner)
    warnings: List[str] = []

    for p in packages:
        if p.version is None or p.version is winner:
            continue
        if VersionComparator.compare_versions(winner_pkg, p):
            pkg_spec = str(p.version)
            winner_spec = str(winner)
            if main_override:
                warnings.append(
                    f"{pkg_name}{pkg_spec} conflicts with main requirement "
                    f"{pkg_name}{winner_spec}; main requirement takes precedence"
                )
            else:
                warnings.append(
                    f"{pkg_name}{pkg_spec} conflicts with selected "
                    f"{pkg_name}{winner_spec}; {pkg_name}{pkg_spec} will not be satisfied"
                )

    return winner, warnings


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

        # Scale subproject weights by recency, then always normalise to sum to 1.
        # Normalisation is unconditional so the math holds when there is no main
        # package (weights would otherwise sum to 1 - main_weight, not 1).
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

    @staticmethod
    def resolve_requirements(
        sub_requirements: Dict[str, Dict[str, Package]],
        outlier_map: Dict[str, List[str]],
        main_sub_name: Optional[str] = None,
    ) -> Dict[str, Package]:
        """Collapse per-subproject requirements into one Package per package name.

        Requirements where the subproject is listed as an outlier for that
        package in outlier_map are dropped. Among the remaining specs for each
        package, the most constrained version is selected via _pick_best_spec.

        If main_sub_name is provided, that subproject's spec is passed as the
        authoritative main_package to _pick_best_spec so conflicting specs are
        detected and logged as warnings before installation.
        """
        collected: Dict[str, List[Package]] = {}
        for sub_name, packages in sub_requirements.items():
            for pkg_name, pkg in packages.items():
                if sub_name in outlier_map.get(pkg_name, []):
                    continue
                collected.setdefault(pkg_name, []).append(pkg)

        result: Dict[str, Package] = {}
        for pkg_name, specs in collected.items():
            main_pkg: Optional[Package] = None
            if main_sub_name and main_sub_name not in outlier_map.get(pkg_name, []):
                main_pkg = sub_requirements.get(main_sub_name, {}).get(pkg_name)

            version, warnings = _pick_best_spec(specs, main_package=main_pkg)
            for w in warnings:
                logger.warning(w)
            result[pkg_name] = Package(name=pkg_name, version=version)

        return result
