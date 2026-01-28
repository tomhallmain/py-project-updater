"""Version specifier and Version model for package requirements."""

from dataclasses import dataclass
from enum import Enum
from packaging import version as pkg_version


class VersionSpecifier(Enum):
    """Enum for different version specifiers."""

    EXACT = "=="
    GREATER_EQUAL = ">="
    LESS_EQUAL = "<="
    GREATER = ">"
    LESS = "<"
    COMPATIBLE = "~="
    NOT_EQUAL = "!="


@dataclass
class Version:
    """Represents a package version with its specifier."""

    specifier: VersionSpecifier
    version: str

    def __str__(self) -> str:
        return f"{self.specifier.value}{self.version}"

    def is_compatible_with(self, other_version: str) -> bool:
        """Check if this version specifier is compatible with another version."""
        try:
            current = pkg_version.parse(self.version)
            other = pkg_version.parse(other_version)

            if self.specifier == VersionSpecifier.EXACT:
                return current == other
            elif self.specifier == VersionSpecifier.GREATER_EQUAL:
                return other >= current
            elif self.specifier == VersionSpecifier.LESS_EQUAL:
                return other <= current
            elif self.specifier == VersionSpecifier.GREATER:
                return other > current
            elif self.specifier == VersionSpecifier.LESS:
                return other < current
            elif self.specifier == VersionSpecifier.COMPATIBLE:
                next_major = pkg_version.Version(f"{current.major + 1}.0.0")
                return other >= current and other < next_major
            elif self.specifier == VersionSpecifier.NOT_EQUAL:
                return other != current
        except pkg_version.InvalidVersion:
            return False
        return False
