#!src/vozdipovo_app/db/migrate.py
from __future__ import annotations

import os
import sqlite3

from vozdipovo_app.db.schema import SCHEMA


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table});").fetchall()
    return {r["name"] for r in rows}


def _add_column_if_missing(conn: sqlite3.Connection, table: str, col_def: str) -> bool:
    col_name = col_def.strip().split()[0]
    if col_name in _columns(conn, table):
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_def};")
    return True


def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _ensure_unique_indexes(conn: sqlite3.Connection) -> bool:
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_news_articles_legal_doc_id_unique
        ON news_articles(legal_doc_id);
        """
    )
    return True


def _apply_migrations(conn: sqlite3.Connection) -> list[str]:
    applied: list[str] = []
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table';"
        ).fetchall()
    }

    if "legal_docs" in tables:
        for col_def in (
            "url_hash TEXT",
            "pub_date TEXT",
            "published_at TEXT",
            "summary TEXT",
            "content_text TEXT",
            "raw_html TEXT",
            "raw_payload_json TEXT",
            "fetched_at TEXT",
        ):
            if _add_column_if_missing(conn, "legal_docs", col_def):
                applied.append(f"add_column=legal_docs.{col_def.split()[0]}")

    if "news_articles" in tables:
        for col_def in ("decision TEXT",):
            if _add_column_if_missing(conn, "news_articles", col_def):
                applied.append(f"add_column=news_articles.{col_def.split()[0]}")

        _ensure_unique_indexes(conn)
        applied.append("ensure_unique_index=news_articles.legal_doc_id")

    return applied


def ensure_schema(db_path: str) -> sqlite3.Connection:
    conn = connect(db_path)
    _ensure_tables(conn)
    applied = _apply_migrations(conn)
    if applied:
        conn.commit()
    return conn


def recreate_schema(db_path: str) -> sqlite3.Connection:
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


if __name__ == "__main__":
    from vozdipovo_app.settings import get_settings

    s = get_settings()
    c = ensure_schema(str(s.db_path))
    try:
        print("ok")
    finally:
        c.close()
