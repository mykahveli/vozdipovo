#!filepath: src/vozdipovo_app/utils/project_paths.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    """Resolved project paths.

    This helper standardizes how the application resolves relative paths,
    avoiding reliance on the current working directory.

    Args:
        root: Project root directory.

    Attributes:
        root: Project root directory.
    """

    root: Path

    @property
    def configs_dir(self) -> Path:
        """Return the configs directory."""
        return (self.root / "configs").resolve()

    @property
    def data_dir(self) -> Path:
        """Return the data directory."""
        return (self.root / "data").resolve()

    @classmethod
    def discover(cls, start: Optional[Path] = None) -> ProjectPaths:
        """Discover the project root by locating a marker file.

        Args:
            start: Optional starting path.

        Returns:
            ProjectPaths: Resolved project paths.
        """
        root = _find_upwards(
            start=start or Path(__file__).resolve(),
            markers=("pyproject.toml", "setup.cfg", "setup.py"),
        )
        return cls(root=root)

    def resolve_relative(self, value: str | Path) -> Path:
        """Resolve a path value relative to the project root.

        Args:
            value: Path value.

        Returns:
            Path: Absolute resolved path.
        """
        p = Path(value).expanduser()
        if p.is_absolute():
            return p.resolve()
        return (self.root / p).resolve()


def _find_upwards(start: Path, markers: Iterable[str]) -> Path:
    start = start.resolve()
    for parent in (start,) + tuple(start.parents):
        for marker in markers:
            if (parent / marker).exists():
                return parent
    return Path.cwd().resolve()
