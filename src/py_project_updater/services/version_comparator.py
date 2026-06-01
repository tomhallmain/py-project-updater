"""Compare package versions between main project and subprojects."""

from packaging import version as pkg_version

from py_project_updater.models import Package, VersionSpecifier
from py_project_updater.models.version import Version

TOLERANCE_LEVELS = ("none", "patch", "minor")

_LOWER_BOUND = {VersionSpecifier.GREATER, VersionSpecifier.GREATER_EQUAL}
_UPPER_BOUND = {VersionSpecifier.LESS, VersionSpecifier.LESS_EQUAL}


class VersionComparator:
    """Compares package versions between main project and subprojects."""

    @staticmethod
    def compare_versions(
        main_package: Package,
        sub_package: Package,
        tolerance: str = "none",
    ) -> bool:
        """Return True if the two packages have a conflict worth reporting.

        Tolerance applies only when both sides carry exact pins (==):
          "none"  – any difference is a conflict (strictest)
          "patch" – only flag if major or minor versions differ
          "minor" – only flag if major versions differ (most lenient)

        For range specifiers the overlap between the two constraints is
        evaluated directly rather than using a proxy version number.
        """
        if not main_package.version or not sub_package.version:
            return False

        try:
            main_v = main_package.version
            sub_v = sub_package.version
            main_spec = main_v.specifier
            sub_spec = sub_v.specifier

            # --- Both exact pins: apply semver tolerance ---
            if main_spec == VersionSpecifier.EXACT and sub_spec == VersionSpecifier.EXACT:
                mp = pkg_version.parse(main_v.version)
                sp = pkg_version.parse(sub_v.version)
                if tolerance == "minor":
                    return mp.major != sp.major
                if tolerance == "patch":
                    return mp.major != sp.major or mp.minor != sp.minor
                return mp != sp  # "none"

            # --- Same-direction range constraints never conflict ---
            # e.g. >=1.25 and >=1.20: any version >=1.25 satisfies both.
            if main_spec in _LOWER_BOUND and sub_spec in _LOWER_BOUND:
                return False
            if main_spec in _UPPER_BOUND and sub_spec in _UPPER_BOUND:
                return False

            # --- Opposing-direction ranges: check boundary overlap ---
            if main_spec in _LOWER_BOUND and sub_spec in _UPPER_BOUND:
                return _no_overlap(main_v, sub_v)
            if main_spec in _UPPER_BOUND and sub_spec in _LOWER_BOUND:
                return _no_overlap(sub_v, main_v)

            # --- Exact vs range: does the exact pin satisfy the range? ---
            if main_spec == VersionSpecifier.EXACT:
                return not sub_v.is_compatible_with(main_v.version)
            if sub_spec == VersionSpecifier.EXACT:
                return not main_v.is_compatible_with(sub_v.version)

            # --- Fallback for ~=, != and mixed edge cases ---
            return not main_v.is_compatible_with(sub_v.version)

        except pkg_version.InvalidVersion:
            return False


def _no_overlap(lower: Version, upper: Version) -> bool:
    """Return True if a lower-bound specifier and an upper-bound specifier cannot overlap."""
    lo = pkg_version.parse(lower.version)
    hi = pkg_version.parse(upper.version)
    if lower.specifier == VersionSpecifier.GREATER_EQUAL and upper.specifier == VersionSpecifier.LESS_EQUAL:
        return lo > hi
    if lower.specifier == VersionSpecifier.GREATER_EQUAL and upper.specifier == VersionSpecifier.LESS:
        return lo >= hi
    if lower.specifier == VersionSpecifier.GREATER and upper.specifier == VersionSpecifier.LESS_EQUAL:
        return lo >= hi
    if lower.specifier == VersionSpecifier.GREATER and upper.specifier == VersionSpecifier.LESS:
        return lo >= hi
    return False
