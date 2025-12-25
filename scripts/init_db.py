#!filepath: scripts/init_db.py
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from vozdipovo_app.db.migrate import ensure_schema


def _default_db_path() -> Path:
    """Build the default DB path.

    Returns:
        Path: Absolute path to the SQLite DB file.
    """
    here = Path(__file__).resolve()
    return (here.parent.parent / "configs" / "vozdipovo.db").resolve()


def main() -> None:
    """Recreate database with the full, consistent schema."""
    db_path = Path(os.getenv("VOZDIPOVO_DB_PATH", str(_default_db_path()))).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path), timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        ensure_schema(conn)
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
