"""Compare package versions between main project and subprojects."""

from packaging import version as pkg_version

from py_project_updater.models import Package, VersionSpecifier


class VersionComparator:
    """Compares package versions between main project and subprojects."""

    @staticmethod
    def compare_versions(main_package: Package, sub_package: Package) -> bool:
        """Compare if versions are significantly different."""
        if not main_package.version or not sub_package.version:
            return False

        try:
            if main_package.version.specifier == VersionSpecifier.EXACT:
                return not sub_package.version.is_compatible_with(main_package.version.version)
            return not main_package.version.is_compatible_with(sub_package.version.version)
        except pkg_version.InvalidVersion:
            return False
