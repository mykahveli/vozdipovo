#!filepath: src/vozdipovo_app/db/connection.py
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional


@dataclass(frozen=True, slots=True)
class DbConfig:
    """Database configuration.

    Attributes:
        path: Path to the SQLite database file.
        timeout_seconds: Busy timeout in seconds.
    """

    path: Path
    timeout_seconds: int = 30


class Db:
    """SQLite connection factory and context manager."""

    def __init__(self, cfg: DbConfig) -> None:
        self._cfg = cfg

    @property
    def path(self) -> Path:
        """Database file path.

        Returns:
            Path: SQLite file path.
        """
        return self._cfg.path

    def connect(self) -> sqlite3.Connection:
        """Create a new sqlite3 connection.

        Returns:
            sqlite3.Connection: Connection instance.
        """
        self._cfg.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._cfg.path), timeout=self._cfg.timeout_seconds)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = ?;", (self._cfg.timeout_seconds * 1000,))
        return conn

    def __enter__(self) -> sqlite3.Connection:
        self._conn = self.connect()
        return self._conn

    def __exit__(self, exc_type, exc, tb) -> None:
        conn: Optional[sqlite3.Connection] = getattr(self, "_conn", None)
        if not conn:
            return
        try:
            if exc_type is None:
                conn.commit()
            else:
                conn.rollback()
        finally:
            conn.close()
