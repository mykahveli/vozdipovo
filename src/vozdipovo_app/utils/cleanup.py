#!filepath: src/vozdipovo_app/utils/cleanup.py
from __future__ import annotations

from pathlib import Path
from typing import Iterable


def remove_macos_resource_forks(paths: Iterable[Path]) -> int:
    """Remove macOS resource fork files (._*) inside given paths.

    Args:
        paths: Directories to scan recursively.

    Returns:
        Number of removed files.
    """
    removed = 0
    for base in paths:
        if not base.exists():
            continue
        for p in base.rglob("._*"):
            if p.is_file():
                try:
                    p.unlink()
                    removed += 1
                except Exception:
                    continue
    return removed
