"""Package model for requirements."""

from dataclasses import dataclass
from typing import Optional

from py_project_updater.models.version import Version, VersionSpecifier


@dataclass
class Package:
    """Represents a Python package with its version requirements."""

    name: str
    version: Optional[Version] = None

    @classmethod
    def from_string(cls, package_str: str) -> "Package":
        """Create a Package instance from a requirements.txt line."""
        if (
            "==" not in package_str
            and ">=" not in package_str
            and "<=" not in package_str
            and ">" not in package_str
            and "<" not in package_str
            and "~=" not in package_str
            and "!=" not in package_str
        ):
            return cls(name=package_str.strip())

        specifiers = [s for s in VersionSpecifier if s.value in package_str]
        if not specifiers:
            return cls(name=package_str.strip())

        specifier = specifiers[0]
        name, ver = package_str.split(specifier.value, 1)
        return cls(name=name.strip(), version=Version(specifier=specifier, version=ver.strip()))

    def __str__(self) -> str:
        if self.version:
            return f"{self.name}{self.version}"
        return self.name
