#!filepath: tools/repo_sanitize.py
from __future__ import annotations

import argparse
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True, slots=True)
class DeletePlan:
    """Plan of filesystem entries to delete.

    Args:
        entries: Paths to delete.
    """

    entries: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class RepoArgs:
    """Parsed CLI arguments.

    Args:
        root: Repository root directory.
        mode: preview or apply.
    """

    root: Path
    mode: str


@dataclass(frozen=True, slots=True)
class RepoSanitizer:
    """Sanitize a repository tree by deleting unwanted artifacts.

    Args:
        root: Repository root directory.
        logger: Logger instance.
    """

    root: Path
    logger: logging.Logger

    @property
    def src_dir(self) -> Path:
        """Return the src directory."""
        return (self.root / "src").resolve()

    @property
    def configs_dir(self) -> Path:
        """Return the configs directory."""
        return (self.root / "configs").resolve()

    def plan(self) -> DeletePlan:
        """Build a deletion plan.

        Returns:
            DeletePlan: Files and directories to delete.
        """
        entries: list[Path] = []

        entries.extend(self._find_dot_underscore_files(self.root))
        entries.extend(self._find_named_dirs(self.root, "__pycache__"))
        entries.extend(self._find_suffix_files(self.root, ".pyc"))

        entries.extend(self._legacy_entries())

        entries.extend(self._sqlite_sidecars())

        uniq = tuple(sorted({p.resolve() for p in entries}))
        return DeletePlan(entries=uniq)

    def apply(self, plan: DeletePlan) -> int:
        """Apply the deletion plan.

        Args:
            plan: Deletion plan.

        Returns:
            int: Number of entries deleted.
        """
        deleted = 0
        for p in plan.entries:
            if self._delete_path(p):
                deleted += 1
        return deleted

    def _legacy_entries(self) -> list[Path]:
        legacy = [
            self.src_dir / "vozdipovo_app" / "editorial" / "schema.py",
            self.src_dir / "vozdipovo_app" / "editorial" / "loader.py",
            self.src_dir / "vozdipovo_app" / "utils" / "config.py",
            self.src_dir / "vozdipovo_app" / "config",
        ]
        return [p for p in legacy if p.exists()]

    def _sqlite_sidecars(self) -> list[Path]:
        sep = chr(45)
        shm = self.configs_dir / f"vozdipovo.db{sep}shm"
        wal = self.configs_dir / f"vozdipovo.db{sep}wal"
        return [p for p in (shm, wal) if p.exists()]

    def _delete_path(self, path: Path) -> bool:
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
            self.logger.info(f"Removido: {path}")
            return True
        except OSError as exc:
            self.logger.error(f"Falha ao remover {path}: {exc}")
            return False

    def _find_dot_underscore_files(self, root: Path) -> Iterable[Path]:
        return root.rglob("._*")

    def _find_named_dirs(self, root: Path, name: str) -> Iterable[Path]:
        for p in root.rglob(name):
            if p.is_dir() and p.name == name:
                yield p

    def _find_suffix_files(self, root: Path, suffix: str) -> Iterable[Path]:
        return root.rglob(f"*{suffix}")


def _discover_repo_root(start: Path) -> Path:
    cur = start.resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / "pyproject.toml").exists():
            return candidate
    return start.resolve()


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode", nargs="?", default="preview", choices=("preview", "apply")
    )
    parser.add_argument("root", nargs="?", default=".")
    return parser


def _parse_args() -> RepoArgs:
    parsed = _build_arg_parser().parse_args()
    root = _discover_repo_root(Path(str(parsed.root)))
    mode = str(parsed.mode).strip().lower()
    return RepoArgs(root=root, mode=mode)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logger = logging.getLogger("repo_sanitize")

    args = _parse_args()

    sanitizer = RepoSanitizer(root=args.root, logger=logger)
    plan = sanitizer.plan()

    for p in plan.entries:
        logger.info(f"Planeado: {p}")

    if args.mode != "apply":
        logger.info("Preview concluído")
        return 0

    deleted = sanitizer.apply(plan)
    logger.info(f"Total removido: {deleted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
