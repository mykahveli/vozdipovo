#!filepath: tests/conftest.py
from __future__ import annotations

import sys
from pathlib import Path


def pytest_configure() -> None:
    """Ensure src layout is importable during tests."""
    root = Path(__file__).resolve().parents[1]
    src = (root / "src").resolve()
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
