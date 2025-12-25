#!src/vozdipovo_app/db/sqlite_conn.py
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Union


def connect_sqlite(db_path: Union[str, Path]) -> sqlite3.Connection:
    """Abre ligação SQLite com defaults seguros.

    Args:
        db_path: Caminho para a base de dados.

    Returns:
        sqlite3.Connection: Ligação ativa.
    """
    p = Path(db_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn
